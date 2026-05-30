import concurrent.futures.process
import logging
import multiprocessing
import os
import time

import reportlab
import reportlab.lib.pagesizes
import reportlab.platypus
from bs4 import BeautifulSoup  # don't need everything, it has several components
from django import db
from django.contrib.sessions.backends.db import SessionStore
from django.db import close_old_connections
from django.template.loader import render_to_string
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

import settings

# Register the LM Roman math font for ReportLab PDF generation. Loaded
# once per process at module import — fresh in each spawn child since
# `multiprocessing.Process(spawn)` re-imports this module. The TTF file
# lives in static/ alongside the WOFF2 variant that the browser uses
# (registered via the @font-face rule in custom.css). The WOFF2 wraps
# CFF outlines and ReportLab can't load CFF-flavored fonts, so we ship
# both files: WOFF2 for browser efficiency, TTF for ReportLab compat.
pdfmetrics.registerFont(
    TTFont("LMRoman10", os.path.join(settings.STATIC_FILES_DIR, "lmroman10-regular.ttf"))
)

import zunzun.forms
from zunzun import platform_compat

from ..parallel_pool import FitPool
from ..session_helpers import load_with_retry, save_with_retry
from . import DataObject, DefaultData, ReportsAndGraphs
from ._unique import (
    new_unique_string,
    page_artifact_filename,
    page_artifact_path,
    page_artifact_url,
)
from .child_payload import ChildPayload

_logger = logging.getLogger(__name__)


class _ReportsPipelineAborted(Exception):
    """Sentinel raised when a parallel phase failure must abort the rest of
    PerformAllWork (PDF generation, HTML rendering, redirect). Caught only
    by PerformAllWork itself; never propagates further."""


def ParallelWorker_CreateReportOutput(inReportObject):
    try:
        if (
            inReportObject.dataObject.equation.GetDisplayName() == "User Defined Function"
        ):  # User Defined Function will not pickle, see http://support.picloud.com/entries/122330-an-error-i-don-t-understand
            inReportObject.dataObject.equation.userDefinedFunctionText = (
                inReportObject.dataObject.userDefinedFunctionText
            )
            inReportObject.dataObject.equation.ParseAndCompileUserFunctionString(
                inReportObject.dataObject.equation.userDefinedFunctionText,
                inReportObject.dataObject.equation.GetDimensionality(),
            )

        inReportObject.CreateReportOutput()

        return [
            inReportObject.name,
            inReportObject.stringList,
            "",
        ]  # name for lookup, stringList for data, empty string for no exception
    except:
        import logging

        s = "\n"
        for item in dir(inReportObject.dataObject):
            if -1 != str(item).find("__"):  # internal python objects
                continue
            if -1 != str(getattr(inReportObject.dataObject, item)).find(
                "bound"
            ):  # internal python objects
                continue

            s += str(item) + ": " + str(getattr(inReportObject.dataObject, item)) + "\n\n"

        logging.exception("Exception creating report, inReportObject.dataObject yields:\n\n" + s)
        return [inReportObject.name, 0, "Exception creating report, see log file"]


def ParallelWorker_CreateCharacterizerOutput(inReportObject):
    try:
        inReportObject.CreateCharacterizerOutput()

        return [
            inReportObject.name,
            inReportObject.stringList,
            "",
        ]  # name for lookup, stringList for data
    except:
        import logging

        logging.exception("Exception characterizer output")

        s = "\n"
        for item in dir(inReportObject.dataObject):
            if -1 != str(item).find("__"):  # internal python objects
                continue
            if -1 != str(getattr(inReportObject.dataObject, item)).find(
                "bound"
            ):  # internal python objects
                continue

            s += str(item) + ": " + str(getattr(inReportObject.dataObject, item)) + "\n\n"

        logging.exception(
            "Exception creating characterizer, inReportObject.dataObject yields:\n\n" + s
        )

        return [inReportObject.name, 0, "Exception characterizer output, see log file"]


# from http://code.activestate.com/recipes/576832-improved-reportlab-recipe-for-page-x-of-y/
class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        """add page info to each page (page x of y)"""
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.setFontSize(7)
        self.drawString(1 * inch, 0.5 * inch, "https://github.com/kiloscheffer/zunzun-ng")
        self.drawRightString(
            (8.5 - 1) * inch, 0.5 * inch, "Page %d of %d" % (self._pageNumber, page_count)
        )


class StatusMonitoredLongRunningProcessPage(object):
    def __init__(self):

        self.oneSecondTimes = 0

        self.inEquationName = ""
        self.inEquationFamilyName = ""

        self.session_data = None
        self.session_functionfinder = None
        self.status_row_pk = None

        self.statisticalDistribution = False
        self.userDefinedFunction = False
        self.spline = False

        self.userInterfaceRequired = True
        self.reniceLevel = 10
        self.completedWorkItemsList = []
        self.boundForm = None
        self.evaluationForm = None

        self.fit_pool = None  # type: ignore[var-annotated]

        self.characterizerOutputTrueOrReportOutputFalse = False
        self.evaluateAtAPointFormNeeded = True

        self.equationInstance = 0

        self.extraExampleDataTextForWeightedFitting = """Weighted fitting requires an additional number to be used as a weight when fitting. The site does not calculate any weights, which are used as:

error = weight * (predicted - actual)

You must provide any weights you wish to use.

"""

        self.defaultData1D = DefaultData.defaultData1D
        self.defaultData2D = DefaultData.defaultData2D
        self.defaultData3D = DefaultData.defaultData3D

    def build_child_payload(self) -> ChildPayload:
        """Produce a picklable snapshot for the spawned child process.

        Default implementation covers the common subset (session keys,
        dimensionality, renice level, dataObject, equation-name/family).
        Subclasses override to add fit-specific fields via the `extra` dict.
        """
        return ChildPayload(
            lrp_class_path=f"{self.__class__.__module__}.{self.__class__.__name__}",
            session_key_data=self.session_key_data,
            session_key_functionfinder=getattr(self, "session_key_functionfinder", ""),
            dimensionality=self.dimensionality,
            renice_level=self.reniceLevel,
            data_object=getattr(self, "dataObject", None),
            equation=None,  # overridden by fit subclasses
            # The LRPStatus row pk this dispatch writes to. The parent
            # (views.LongRunningProcessView) creates the row and sets
            # self.status_row_pk before this build runs; the getattr
            # fallback to 0 is defensive (an update against pk=0 matches
            # zero rows, harmless).
            status_row_pk=getattr(self, "status_row_pk", 0),
            extra={
                # inEquationName / inEquationFamilyName are set by
                # views.LongRunningProcessView (parent) from URL path
                # segments. Read in the child by:
                #  - CreateReportPDF (pdf title paragraph)
                #  - Each Fit* subclass's SaveSpecificDataToSessionStore
                #    which writes them to the 'data' session so that
                #    EvaluateAtAPointView can later reconstruct the
                #    equation by name/family.
                # Without explicit transport the child sees the __init__
                # defaults (empty strings), the session stores empty
                # strings, and Evaluate-at-a-Point returns
                # "Could not find the equation '' in the equation family ''."
                "inEquationName": getattr(self, "inEquationName", ""),
                "inEquationFamilyName": getattr(self, "inEquationFamilyName", ""),
            },
        )

    def apply_child_payload(self, payload: ChildPayload) -> None:
        """Re-hydrate this instance (in the child process) from the payload.

        Default implementation restores the common fields. Subclasses
        override to populate fit-specific state from payload.extra.
        """
        self.session_key_data = payload.session_key_data
        self.session_key_functionfinder = payload.session_key_functionfinder
        self.dimensionality = payload.dimensionality
        self.reniceLevel = payload.renice_level
        self.dataObject = payload.data_object
        self.inEquationName = payload.extra.get("inEquationName", "")
        self.inEquationFamilyName = payload.extra.get("inEquationFamilyName", "")
        # The LRPStatus row pk this dispatch writes to. _run_fit_child
        # also sets this directly from the payload before
        # apply_child_payload runs (same value, harmless redundancy,
        # mirrors how session_key_* are set in both places).
        self.status_row_pk = payload.status_row_pk

    def PerformWorkInParallel(self):
        pass

    def SaveSpecificDataToSessionStore(self):
        pass

    def GenerateListOfWorkItems(self):
        pass

    def CreateReportPDF(self):

        self.update_status(current_status="Creating PDF Output File")
        try:
            scale = 72.0 / 300.0  # dpi conversion factor for PDF file images

            self.pdfFileName = page_artifact_filename(self.dataObject.uniqueString, "pdf")
            pageElements = []

            styles = reportlab.lib.styles.getSampleStyleSheet()

            styles.add(
                reportlab.lib.styles.ParagraphStyle(
                    name="CenteredBodyText",
                    parent=styles["BodyText"],
                    alignment=reportlab.lib.enums.TA_CENTER,
                )
            )
            styles.add(
                reportlab.lib.styles.ParagraphStyle(
                    name="SmallCenteredBodyText",
                    parent=styles["BodyText"],
                    fontSize=8,
                    alignment=reportlab.lib.enums.TA_CENTER,
                )
            )
            styles.add(
                reportlab.lib.styles.ParagraphStyle(
                    name="SmallCode",
                    parent=styles["Code"],
                    fontSize=8,
                    alignment=reportlab.lib.enums.TA_LEFT,
                    leftIndent=0,
                )
            )  # 'Code' and wordwrap=CJK causes problems

            myTableStyle = [
                ("FACE", (1, 0), (1, 0), "Helvetica-Bold"),
                ("SIZE", (1, 0), (1, 0), 22),
                ("VALIGN", (1, 0), (1, 0), "TOP"),
            ]

            largeLogoImage = reportlab.platypus.Image(
                os.path.join(settings.STATIC_FILES_DIR, "logo.png"), 37 * scale * 3, 37 * scale * 3
            )

            tableRow = [largeLogoImage, "ZunZunNG", largeLogoImage]

            table = reportlab.platypus.Table([tableRow], style=myTableStyle)

            pageElements.append(table)

            pageElements.append(
                reportlab.platypus.XPreformatted(
                    "&nbsp;\n&nbsp;\n&nbsp;\n&nbsp;\n", styles["CenteredBodyText"]
                )
            )

            if self.inEquationName:
                pageElements.append(
                    reportlab.platypus.Paragraph(self.inEquationName, styles["CenteredBodyText"])
                )

            titleXML = (
                self.pdfTitleHTML.replace("sup>", "super>")
                .replace("SUP>", "super>")
                .replace("<br>", "<br/>")
                .replace("<BR>", "<br/>")
            )
            pageElements.append(reportlab.platypus.Paragraph(titleXML, styles["CenteredBodyText"]))

            pageElements.append(
                reportlab.platypus.XPreformatted("&nbsp;\n&nbsp;\n", styles["CenteredBodyText"])
            )
            pageElements.append(
                reportlab.platypus.Paragraph(
                    time.asctime(time.localtime()) + " local server time",
                    styles["SmallCenteredBodyText"],
                )
            )

            pageElements.append(reportlab.platypus.PageBreak())

            # make a page for each report output, with report name as page header
            # graphs may not exist if they raised an exception at creation time, trap and handle this condition
            for report in self.textReports:
                pageElements.append(
                    reportlab.platypus.Preformatted(report.name, styles["SmallCode"])
                )
                pageElements.append(
                    reportlab.platypus.XPreformatted(
                        "&nbsp;\n&nbsp;\n&nbsp;\n", styles["SmallCode"]
                    )
                )

                if report.stringList[0] == "</pre>":  # corrects fit statistics not in PDF
                    report.stringList = report.stringList[1:]

                joinedString = str("\n").join(report.stringList)

                if -1 != report.name.find("Coefficients"):
                    joinedString = joinedString.replace("<sup>", "^")
                    joinedString = joinedString.replace("<SUP>", "^")

                soup = BeautifulSoup(joinedString, "lxml")

                notUnicodeList = []
                for i in soup.findAll(text=True):
                    notUnicodeList.append(str(i))
                replacedText = str("").join(notUnicodeList)

                replacedText = replacedText.replace("\t", "    ")  # convert tabs to four spaces
                replacedText = replacedText.replace("\r\n", "\n")

                rebuiltText = ""
                for line in replacedText.split("\n"):
                    if line == "":
                        rebuiltText += "\n"
                    else:
                        if line[0] == "<":
                            splitLine = line.split(">")
                            if len(splitLine) > 1:
                                newLine = splitLine[len(splitLine) - 1]
                            else:
                                newLine = ""
                        else:
                            newLine = line

                        # crude line wrapping
                        if len(newLine) > 500:
                            rebuiltText += newLine[:100] + "\n"
                            rebuiltText += newLine[100:200] + "\n"
                            rebuiltText += newLine[200:300] + "\n"
                            rebuiltText += newLine[300:400] + "\n"
                            rebuiltText += newLine[400:500] + "\n"
                            rebuiltText += newLine[500:] + "\n"
                        elif len(newLine) > 400:
                            rebuiltText += newLine[:100] + "\n"
                            rebuiltText += newLine[100:200] + "\n"
                            rebuiltText += newLine[200:300] + "\n"
                            rebuiltText += newLine[300:400] + "\n"
                            rebuiltText += newLine[400:] + "\n"
                        elif len(newLine) > 300:
                            rebuiltText += newLine[:100] + "\n"
                            rebuiltText += newLine[100:200] + "\n"
                            rebuiltText += newLine[200:300] + "\n"
                            rebuiltText += newLine[300:] + "\n"
                        elif len(newLine) > 200:
                            rebuiltText += newLine[:100] + "\n"
                            rebuiltText += newLine[100:200] + "\n"
                            rebuiltText += newLine[200:] + "\n"
                        elif len(newLine) > 100:
                            rebuiltText += newLine[:100] + "\n"
                            rebuiltText += newLine[100:] + "\n"
                        else:
                            rebuiltText += newLine + "\n"

                pageElements.append(
                    reportlab.platypus.Preformatted(rebuiltText, styles["SmallCode"])
                )

                pageElements.append(reportlab.platypus.PageBreak())

            for report in self.graphReports:
                if report.animationFlag:  # pdf files cannot contain GIF animations
                    continue
                if os.path.isfile(report.physicalFileLocation):
                    pageElements.append(
                        reportlab.platypus.Paragraph(report.name, styles["CenteredBodyText"])
                    )
                    pageElements.append(
                        reportlab.platypus.XPreformatted(
                            "&nbsp;\n&nbsp;\n", styles["CenteredBodyText"]
                        )
                    )
                    try:
                        im = reportlab.platypus.Image(
                            report.physicalFileLocation,
                            self.dataObject.graphWidth * scale,
                            self.dataObject.graphHeight * scale,
                        )
                    except:
                        time.sleep(1.0)
                        im = reportlab.platypus.Image(
                            report.physicalFileLocation,
                            self.dataObject.graphWidth * scale,
                            self.dataObject.graphHeight * scale,
                        )
                    im.hAlign = "CENTER"
                    pageElements.append(im)
                    if report.stringList != []:
                        pageElements.append(
                            reportlab.platypus.Preformatted(report.name, styles["SmallCode"])
                        )
                        pageElements.append(
                            reportlab.platypus.XPreformatted(
                                "&nbsp;\n&nbsp;\n&nbsp;\n", styles["CenteredBodyText"]
                            )
                        )
                        for line in report.stringList:
                            replacedLine = (
                                line.replace("<br>", "\n")
                                .replace("<BR>", "\n")
                                .replace("<pre>", "")
                                .replace("</pre>", "")
                                .replace("<tr>", "")
                                .replace("</tr>", "")
                                .replace("<td>", "")
                                .replace("</td>", "")
                                .replace("sup>", "super>")
                                .replace("SUP>", "super>")
                                .replace("\r\n", "\n")
                                .replace("&nbsp;", " ")
                            )
                            pageElements.append(
                                reportlab.platypus.XPreformatted(replacedLine, styles["SmallCode"])
                            )

                pageElements.append(reportlab.platypus.PageBreak())

            try:
                doc = reportlab.platypus.SimpleDocTemplate(
                    os.path.join(settings.TEMP_FILES_DIR, self.pdfFileName),
                    pagesize=reportlab.lib.pagesizes.letter,
                )
                doc.build(pageElements, canvasmaker=NumberedCanvas)
            except:
                time.sleep(1.0)
                doc = reportlab.platypus.SimpleDocTemplate(
                    os.path.join(settings.TEMP_FILES_DIR, self.pdfFileName),
                    pagesize=reportlab.lib.pagesizes.letter,
                )
                doc.build(pageElements, canvasmaker=NumberedCanvas)
        except:
            import logging

            logging.exception("Exception creating PDF file")

            self.pdfFileName = ""  # empty string used as a flag

    def BaseCreateAndInitializeDataObject(self, xName, yName, zName):
        dataObject = DataObject.DataObject()

        dataObject.ErrorString = ""
        dataObject.logLinX = "LIN"
        dataObject.logLinY = "LIN"
        dataObject.logLinZ = "LIN"

        settings.TEMP_FILES_DIR = settings.TEMP_FILES_DIR
        dataObject.WebsiteImageLocation = settings.MEDIA_URL

        dataObject.dimensionality = self.dimensionality

        dataObject.IndependentDataName1 = xName
        if dataObject.dimensionality > 1:
            dataObject.IndependentDataName2 = ""
            dataObject.DependentDataName = yName
        if dataObject.dimensionality > 2:
            dataObject.IndependentDataName2 = yName
            dataObject.DependentDataName = zName

        dataObject.uniqueString = new_unique_string()
        dataObject.physicalStatusFileName = page_artifact_path(dataObject.uniqueString, "html")
        dataObject.websiteStatusFileName = page_artifact_url(dataObject.uniqueString, "html")

        return dataObject

    def CommonCreateAndInitializeDataObject(self, FF=False):

        self.dataObject = self.BaseCreateAndInitializeDataObject("", "", "")
        self.dataObject.equation = 0
        self.dataObject.fittedStatisticalDistributionsList = []
        self.dataObject.IndependentDataArray = self.boundForm.cleaned_data["IndependentData"]
        if self.dataObject.dimensionality > 1:
            self.dataObject.DependentDataArray = self.boundForm.cleaned_data["DependentData"]

        self.dataObject.IndependentDataName1 = self.boundForm.cleaned_data["dataNameX"]
        if self.dataObject.dimensionality > 1:
            self.dataObject.IndependentDataName2 = ""
            self.dataObject.DependentDataName = self.boundForm.cleaned_data["dataNameY"]
        if self.dataObject.dimensionality > 2:
            self.dataObject.IndependentDataName2 = self.boundForm.cleaned_data["dataNameY"]
            self.dataObject.DependentDataName = self.boundForm.cleaned_data["dataNameZ"]
            try:
                self.dataObject.dataPointSize3D = self.boundForm.cleaned_data["dataPointSize3D"]
            except:
                pass

        if self.dataObject.dimensionality == 2:
            self.dataObject.logLinX = self.boundForm.cleaned_data["logLinX"]
            self.dataObject.logLinY = self.boundForm.cleaned_data["logLinY"]

        if True == FF:  # function finder, return here
            return self.dataObject

        self.dataObject.graphWidth = int(self.boundForm.cleaned_data["graphSize"].split("x")[0])
        self.dataObject.graphHeight = int(self.boundForm.cleaned_data["graphSize"].split("x")[1])

        if self.dataObject.dimensionality > 1:
            self.dataObject.Extrapolation_x = self.boundForm.cleaned_data["graphScaleX"]
            self.dataObject.Extrapolation_x_min = self.boundForm.cleaned_data["minManualScaleX"]
            self.dataObject.Extrapolation_x_max = self.boundForm.cleaned_data["maxManualScaleX"]

            self.dataObject.ScientificNotationX = self.boundForm.cleaned_data["scientificNotationX"]
            self.dataObject.ScientificNotationY = self.boundForm.cleaned_data["scientificNotationY"]
            self.dataObject.Extrapolation_y = self.boundForm.cleaned_data["graphScaleY"]
            self.dataObject.Extrapolation_y_min = self.boundForm.cleaned_data["minManualScaleY"]
            self.dataObject.Extrapolation_y_max = self.boundForm.cleaned_data["maxManualScaleY"]

        if self.dataObject.dimensionality > 2:
            self.dataObject.animationWidth = int(
                self.boundForm.cleaned_data["animationSize"].split("x")[0]
            )
            self.dataObject.animationHeight = int(
                self.boundForm.cleaned_data["animationSize"].split("x")[1]
            )
            self.dataObject.ScientificNotationZ = self.boundForm.cleaned_data["scientificNotationZ"]
            self.dataObject.Extrapolation_z = self.boundForm.cleaned_data["graphScaleZ"]
            self.dataObject.Extrapolation_z_min = self.boundForm.cleaned_data["minManualScaleZ"]
            self.dataObject.Extrapolation_z_max = self.boundForm.cleaned_data["maxManualScaleZ"]
            self.dataObject.logLinZ = self.boundForm.cleaned_data["logLinZ"]

        # can only take log of positive data
        if self.dataObject.logLinX == "LOG" and min(self.dataObject.IndependentDataArray[0]) <= 0.0:
            self.dataObject.ErrorString = (
                "Your X data ("
                + self.dataObject.IndependentDataName1
                + ") contains a non-positive value and you have selected logarithmic X scaling. I cannot take the log of a non-positive number."
            )
        if self.dataObject.dimensionality == 2:
            if self.dataObject.logLinY == "LOG" and min(self.dataObject.DependentDataArray) <= 0.0:
                self.dataObject.ErrorString = (
                    "Your Y data ("
                    + self.dataObject.DependentDataName
                    + ") contains a non-positive value and you have selected logarithmic Y scaling. I cannot take the log of a non-positive number."
                )
        if self.dataObject.dimensionality == 3:
            if (
                self.dataObject.logLinY == "LOG"
                and min(self.dataObject.IndependentDataArray[1]) <= 0.0
            ):
                self.dataObject.ErrorString = (
                    "Your Y data ("
                    + self.dataObject.IndependentDataName1
                    + ") contains a non-positive value and you have selected logarithmic Y scaling. I cannot take the log of a non-positive number."
                )
            if self.dataObject.logLinZ == "LOG" and min(self.dataObject.DependentDataArray) <= 0.0:
                self.dataObject.ErrorString = (
                    "Your Z data ("
                    + self.dataObject.DependentDataName
                    + ") contains a non-positive value and you have selected logarithmic Z scaling. I cannot take the log of a non-positive number."
                )

        if self.dataObject.dimensionality == 3:
            self.dataObject.animationWidth = int(
                self.boundForm.cleaned_data["animationSize"].split("x")[0]
            )
            self.dataObject.animationHeight = int(
                self.boundForm.cleaned_data["animationSize"].split("x")[1]
            )
            self.dataObject.azimuth3D = float(self.boundForm.cleaned_data["rotationAnglesAzimuth"])
            self.dataObject.altimuth3D = float(
                self.boundForm.cleaned_data["rotationAnglesAltimuth"]
            )

    def SaveDictionaryOfItemsToSessionStore(self, inSessionStoreName, inDictionary):
        _logger.debug(inSessionStoreName)

        session = getattr(self, "session_" + inSessionStoreName)
        if session is None:
            _logger.debug("No session in sessionstore, creating new session")
            session = SessionStore(getattr(self, "session_key_" + inSessionStoreName))

        for i in list(inDictionary.keys()):
            item = inDictionary[i]
            _logger.debug(str(i) + " type: " + str(type(item)))
            # Store the raw value. Callers are responsible for producing
            # JSON-native values (no numpy scalars, sets, or datetime).
            session[i] = item
            _logger.debug(str(i) + " saved to session")

        save_with_retry(session)

        db.connections.close_all()
        close_old_connections()
        session = None

    def LoadItemFromSessionStore(self, inSessionStoreName, inItemName):

        session = getattr(self, "session_" + inSessionStoreName)
        if session is None:
            session = SessionStore(getattr(self, "session_key_" + inSessionStoreName))
        returnItem = load_with_retry(session, inItemName)
        db.connections.close_all()
        close_old_connections()
        session = None

        return returnItem

    def update_status(self, **fields):
        """Write fields to this dispatch's LRPStatus row. Unconditional,
        single-row UPDATE — no ownership check (each fit owns its own row).
        A missing/deleted row (e.g., superseded by a newer dispatch that
        deleted it) matches zero rows and is a harmless no-op.
        """
        from zunzun.models import LRPStatus

        LRPStatus.objects.filter(pk=self.status_row_pk).update(**fields)

    def get_status(self, field, default=None):
        """Read one field from this dispatch's LRPStatus row. Returns
        `default` ONLY when the row is missing — a falsy stored value
        (process_id=0, redirect_to_results="") round-trips as itself.
        """
        from zunzun.models import LRPStatus

        row = LRPStatus.objects.filter(pk=self.status_row_pk).values(field).first()
        return row[field] if row is not None else default

    def _write_terminal_error_html(self, error_message):
        """Render a terminal error page to the dataObject's artifact path
        and return that path. Returns None only if disk is unwritable.

        Used by the abort sites that raise _ReportsPipelineAborted
        (BrokenProcessPool, FunctionFinder/StatisticalDistributions
        pool failures). Without a terminal artifact + redirect, those
        paths only update currentStatus, and since PerformAllWork's
        `except _ReportsPipelineAborted: pass` doesn't propagate to
        _run_fit_child, the polling UI stays stuck forever.

        Tiered fallback mirrors RenderOutputHTMLToAFileAndSetStatusRedirect:
          1. Django template render of generic_error.html
          2. Hardcoded HTML string (template loader broken)
        Both layers use the same artifact path so the redirect is
        single-pointer regardless of which succeeds. Returns None ONLY
        when the disk itself is unwritable (full, permission denied) —
        callers can treat that as "skip the redirect" knowing this is
        the truly unrecoverable case, not a transient template hiccup.
        """
        try:
            error_html_path = page_artifact_path(self.dataObject.uniqueString, "html")
        except Exception:
            import logging

            logging.exception("Could not compute terminal-error artifact path")
            return None

        try:
            with open(error_html_path, "w", encoding="utf-8") as f:
                f.write(render_to_string("zunzun/generic_error.html", {"error": error_message}))
            return error_html_path
        except Exception:
            import logging

            logging.exception("Failed to render generic_error.html; trying static fallback")

        # Fallback: hardcoded HTML, no Django dependency. Only fails
        # if disk itself is unwritable.
        try:
            with open(error_html_path, "w", encoding="utf-8") as f:
                f.write(
                    "<html><head><title>ZunZunNG - Error</title></head>"
                    "<body><h2>Error</h2><p>"
                    + (error_message or "An internal error occurred.")
                    + "</p></body></html>"
                )
            return error_html_path
        except Exception:
            import logging

            logging.exception("Also failed to write static fallback HTML")
            return None

    def PerformAllWork(self):

        self.fit_pool = FitPool()
        try:
            self.update_status(process_id=os.getpid())

            self.GenerateListOfWorkItems()

            self.PerformWorkInParallel()

            self.GenerateListOfOutputReports()

            self.CreateOutputReportsInParallelUsingProcessPool()

            self.CreateReportPDF()

            self.RenderOutputHTMLToAFileAndSetStatusRedirect()

            # Success terminal: clear process_id and mark completed so the
            # per-user gate (views.LongRunningProcessView) doesn't block this
            # user's next fit. completed survives StatusView clearing
            # redirect_to_results, so a fast fit the user views within 60s
            # doesn't falsely re-enter the gate's pending window. This
            # dispatch owns its own row, so no ownership check is needed.
            # start_time is left intact for the status template's elapsed
            # timer.
            self.update_status(process_id=0, completed=True)

        except _ReportsPipelineAborted:
            # The reports phase wrote its own user-visible status AND
            # terminal redirect (via update_status /
            # _write_terminal_error_html); do not run CreateReportPDF
            # or RenderOutputHTML, which would overwrite that redirect
            # with a path to an empty results page. The finally block
            # still tears down the pool; the status page completes via
            # the abort site's terminal redirect within one poll cycle.
            pass
        finally:
            if self.fit_pool is not None:
                self.fit_pool.shutdown(wait=True)
                self.fit_pool = None
            # Catch-all clear for unhandled exceptions that escape the
            # try AND aren't _ReportsPipelineAborted (PDF render bug,
            # scipy/numpy crash, DB error). Clears process_id so the
            # per-user gate's is_active check is released.
            #
            # Deliberately does NOT set completed=True here. On the
            # unhandled-exception path the exception propagates to
            # _run_fit_child's except-branch, which writes the terminal
            # error artifact and publishes its path to redirect_to_results
            # — but only if the row is not ALREADY completed (its
            # `already_completed` guard exists to avoid clobbering a served
            # success). If this finally pre-set completed=True, that guard
            # would skip the error redirect and orphan the artifact, leaving
            # the user on the generic "no results" page. So `completed` is
            # left for a real terminal writer to set: the success path
            # (above), the abort sites, or _run_fit_child's handler (which
            # always sets it). The gate is still released in every failure
            # path because that handler sets process_id=0 + completed=True.
            # This dispatch owns its own row, so the update only touches our
            # row (a superseding dispatch deleted it → zero rows).
            try:
                self.update_status(process_id=0)
            except Exception:
                pass  # finally cleanup must not raise

    def CreateOutputReportsInParallelUsingProcessPool(self):

        self.update_status(current_status="Running All Reports")

        reportsToBeRunInParallel = self.graphReports + self.textReports
        totalNumberOfReportsToBeRun = len(reportsToBeRunInParallel)

        if totalNumberOfReportsToBeRun == 0:
            self.update_status(parallel_count=0)
            return

        # Pre-flight: User Defined Function pickle workaround. The compiled
        # function code object is not picklable; null it out before submit
        # so spawn workers receive a transportable shape.
        for item in reportsToBeRunInParallel:
            try:
                item.dataObject.equation.modelRelativeError
            except AttributeError:
                item.dataObject.equation.modelRelativeError = None
            if (
                not self.characterizerOutputTrueOrReportOutputFalse
                and item.dataObject.equation.GetDisplayName() == "User Defined Function"
            ):
                item.dataObject.userDefinedFunctionText = (
                    item.dataObject.equation.userDefinedFunctionText
                )
                item.dataObject.equation.userFunctionCodeObject = None
                item.dataObject.equation.safe_dict = None

        worker_fn = (
            ParallelWorker_CreateCharacterizerOutput
            if self.characterizerOutputTrueOrReportOutputFalse
            else ParallelWorker_CreateReportOutput
        )

        countOfReportsRun = 0

        def _progress(done: int, _total: int) -> None:
            nonlocal countOfReportsRun
            countOfReportsRun = done
            self.Reports_CheckOneSecondSessionUpdates(
                countOfReportsRun, totalNumberOfReportsToBeRun
            )

        # Pre-build a name → report dict so per-result lookup is O(1)
        # instead of an O(N) scan. Reports are usually unique by name
        # within one fit (see ReportsAndGraphs.FittingReportsDict);
        # FunctionFinderResults can append multiple instances of the
        # same plot class with identical class-level names when
        # numberOfEquationsToDisplay > 1. setdefault preserves the
        # legacy linear-scan-with-break semantics (first occurrence
        # wins) rather than the dict-comprehension last-wins default.
        report_by_name: dict = {}
        for r in reportsToBeRunInParallel:
            report_by_name.setdefault(r.name, r)

        try:
            for returnedValue in self.fit_pool.submit_many(
                worker_fn, reportsToBeRunInParallel, progress=_progress
            ):
                report = report_by_name.get(returnedValue[0])
                if report is not None:
                    if returnedValue[2]:  # exception during parallel processing
                        report.exception = True
                    report.stringList = returnedValue[1]
        except concurrent.futures.process.BrokenProcessPool:
            import logging

            logging.exception("BrokenProcessPool in CreateOutputReportsInParallelUsingProcessPool")
            # Publish terminal redirect + status text directly to this
            # dispatch's row so the polling UI completes — PerformAllWork's
            # `except _ReportsPipelineAborted: pass` swallows the abort
            # without propagating to _run_fit_child.
            error_message = (
                "An internal error occurred during report generation. "
                "Please try again or contact the administrator."
            )
            self.update_status(
                redirect_to_results=self._write_terminal_error_html(error_message) or "",
                process_id=0,
                completed=True,
                current_status=error_message,
                parallel_count=0,
            )
            raise _ReportsPipelineAborted()

        self.update_status(parallel_count=0)

    def _oneSecondStatusUpdate(self, currentStatus):
        """Throttled (≤1Hz) liveness + status write for tight work loops.

        Per second: runs ``CheckIfStillUsed`` to detect abandoned fits,
        writes the supplied ``currentStatus`` (into the row's
        ``current_status`` field) plus the current ``parallel_count`` to
        this dispatch's LRPStatus row (via ``update_status``), and bumps
        ``self.oneSecondTimes``. Returns immediately if a second hasn't
        elapsed since the last call.

        ``parallel_count`` is its own LRPStatus field so the status page
        renders it next to the elapsed timer instead of wedged into
        ``current_status``. UI hides the indicator when the count is ≤1
        (single-thread phases or pool idle).

        Used by ``Reports_CheckOneSecondSessionUpdates`` here, and by
        the equivalent ``WorkItems_*`` methods on the FunctionFinder and
        StatisticalDistributions subclasses.
        """
        if self.oneSecondTimes == int(time.time()):
            return
        self.CheckIfStillUsed()
        self.update_status(
            current_status=currentStatus,
            parallel_count=len(multiprocessing.active_children()),
        )
        self.oneSecondTimes = int(time.time())

    def Reports_CheckOneSecondSessionUpdates(self, countOfReportsRun, totalNumberOfReportsToBeRun):
        self._oneSecondStatusUpdate(
            "Created %s of %s Reports and Graphs" % (countOfReportsRun, totalNumberOfReportsToBeRun)
        )

    def _teardown_abandoned_fit(self):
        """Tear down this fit's pools and terminate its worker children.

        Called by CheckIfStillUsed when the fit is determined abandoned or
        superseded (the row was deleted by a newer dispatch, a foreign pid
        claimed it, or the heartbeat went stale). ``shutdown(cancel_futures=
        True)`` only cancels PENDING futures; workers mid-fit keep running
        until their task finishes, so we also ``terminate()`` the live
        children to free CPU/RAM immediately.
        """
        import time

        time.sleep(1.0)
        if self.fit_pool is not None:
            self.fit_pool.shutdown(wait=False, cancel_futures=True)
            self.fit_pool = None
        # FunctionFinder's per-fit sub-pool, if present
        if getattr(self, "ff_pool", None) is not None:
            self.ff_pool.shutdown(wait=False, cancel_futures=True)
            self.ff_pool = None
        for p in multiprocessing.active_children():
            p.terminate()

    def CheckIfStillUsed(self):
        import time

        running_pid = self.get_status("process_id")
        # A None process_id means the row is gone — a newer dispatch
        # superseded this one and deleted the row (delete-prior-row in
        # LongRunningProcessView), or the housekeeping age-sweep reclaimed it.
        # Either way this fit is abandoned: tear it down so a superseded
        # CPU-heavy fit doesn't keep saturating cores until it finishes on its
        # own. (update_status against the deleted pk stays a harmless no-op;
        # the *resource* leak is what this teardown addresses — without it the
        # superseded child can no longer observe the foreign-pid or stale-
        # heartbeat triggers below, because the row carrying them is gone.)
        #
        # Teardown alone is NOT enough: it kills the pools/worker children, but
        # the LRP child's OWN control flow continues — e.g. FunctionFinder's
        # all-linear serialWorker fits in this very process with no pool child
        # to terminate, and the report/scan loops would proceed through the
        # rest of PerformAllWork. So after teardown we raise
        # _ReportsPipelineAborted (the same sentinel the pool-death sites use);
        # PerformAllWork catches it and halts the child. No terminal redirect is
        # written, which is correct: in every abandonment case nobody is
        # watching THIS row (the user's session points at the newer dispatch's
        # row, or the client stopped polling), and update_status on a deleted
        # row is a no-op anyway.
        if running_pid is None:
            self._teardown_abandoned_fit()
            raise _ReportsPipelineAborted()

        # if a new process ID is in the row, another process was started and
        # this process was abandoned
        if running_pid != os.getpid() and running_pid != 0:
            self._teardown_abandoned_fit()
            raise _ReportsPipelineAborted()

        # if the status has not been checked in the past 300 seconds, this
        # process was abandoned. last_status_check is the StatusUpdateView
        # heartbeat. The parent stamps it = start_time at dispatch
        # (LongRunningProcessView), so in normal operation it is never 0.0
        # here. The start_time fallback below is belt-and-suspenders for the
        # should-not-occur case where the row somehow has last_status_check=0.0
        # (e.g. a row created outside the view path); without it such a fit
        # would self-terminate before its first poll.
        last_check = self.get_status("last_status_check") or 0.0
        if not last_check:
            last_check = self.get_status("start_time") or time.time()
        if (time.time() - last_check) > 300:
            self._teardown_abandoned_fit()
            raise _ReportsPipelineAborted()

    def SetInitialStatusDataIntoSessionVariables(self, request):
        # The status row is created by the parent (views.LongRunningProcessView)
        # before the child spawns, so there is no status write here — only
        # the 'data' blob the later EvaluateAtAPointView reads.
        self.SaveDictionaryOfItemsToSessionStore(
            "data",
            {
                "textDataEditor_" + str(self.dimensionality) + "D": request.POST["textDataEditor"],
                "commaConversion": request.POST["commaConversion"],
                "IndependentDataName1": self.dataObject.IndependentDataName1,
                "IndependentDataName2": self.dataObject.IndependentDataName2,
                "DependentDataName": self.dataObject.DependentDataName,
            },
        )

    def SpecificCodeForGeneratingListOfOutputReports(self):

        self.functionString = "PrepareForReportOutput"
        self.update_status(current_status="Calculating Error Statistics")
        self.dataObject.CalculateErrorStatistics()

        self.update_status(current_status="Calculating Parameter Statistics")
        self.dataObject.equation.CalculateCoefficientAndFitStatistics()

        self.update_status(current_status="Generating Report Objects")
        self.ReportsAndGraphsCategoryDict = ReportsAndGraphs.FittingReportsDict(self.dataObject)

    def GenerateListOfOutputReports(self):

        self.textReports = []
        self.graphReports = []

        # calculate data statistics and graph boundaries
        self.update_status(current_status="Calculating Data Statistics")
        self.dataObject.CalculateDataStatistics()

        if self.dataObject.dimensionality > 1:
            self.update_status(current_status="Calculating Graph Boundaries")
            self.dataObject.CalculateGraphBoundaries()

        self.SpecificCodeForGeneratingListOfOutputReports()

        # generate required text reports
        self.update_status(current_status="Generating List Of Text Reports")
        for i in self.ReportsAndGraphsCategoryDict["Text Reports"]:
            exec("i." + self.functionString + "()")
            if i.name != "":
                self.textReports.append(i)

        # select required graph reports
        self.update_status(current_status="Generating List Of Graphical Reports")
        for i in self.ReportsAndGraphsCategoryDict["Graph Reports"]:
            exec("i." + self.functionString + "()")
            if i.name != "":
                self.graphReports.append(i)

    def RenderOutputHTMLToAFileAndSetStatusRedirect(self):

        # If a newer dispatch superseded this one it deleted our status row
        # (delete-prior-row in LongRunningProcessView). SaveSpecificDataToSessionStore
        # below writes the per-SESSION-shared `data` blob that EvaluateAtAPoint
        # later reads; a superseded child writing it would clobber the winning
        # dispatch's data. A missing row (get_status -> None) is the
        # supersession signal — skip all shared-state writes (the terminal
        # redirect would be a no-op on the deleted row anyway).
        if self.get_status("process_id") is None:
            return

        self.SaveSpecificDataToSessionStore()

        self.update_status(current_status="Generating Output HTML")

        itemsToRender = {}

        itemsToRender["dimensionality"] = str(self.dimensionality)

        itemsToRender["header_text"] = "ZunZunNG"
        itemsToRender["subtitle_text"] = self.webFormName
        itemsToRender["title_string"] = "ZunZunNG - " + self.webFormName.replace(
            "<br>", " "
        ).replace('<span class="math">', "").replace("</span>", "")

        itemsToRender["textReports"] = self.textReports

        # get animation file sizes
        for i in self.graphReports:
            if i.animationFlag:
                try:
                    fileBytes = os.path.getsize(i.physicalFileLocation)
                except:
                    fileBytes = 0

                # from https://stackoverflow.com/questions/14996453/python-libraries-to-calculate-human-readable-filesize-from-bytes
                suffixes = ["Bytes", "KBytes", "MBytes", "GBytes", "TBytes", "PBytes"]
                idx = 0
                while fileBytes >= 1024 and idx < len(suffixes) - 1:
                    fileBytes /= 1024.0
                    idx += 1
                f = ("%.2f" % fileBytes).rstrip("0").rstrip(".")
                i.fileSize = "%s %s" % (f, suffixes[idx])

        itemsToRender["graphReports"] = self.graphReports

        itemsToRender["pdfFileName"] = self.pdfFileName

        itemsToRender["statisticalDistributions"] = self.statisticalDistribution

        itemsToRender["feedbackForm"] = zunzun.forms.FeedbackForm()

        itemsToRender["equationInstance"] = self.equationInstance
        if self.evaluateAtAPointFormNeeded:
            itemsToRender["EvaluateAtAPointForm"] = getattr(
                zunzun.forms, "EvaluateAtAPointForm_" + str(self.dimensionality) + "D"
            )()
            itemsToRender["IndependentDataName1"] = self.dataObject.IndependentDataName1
            itemsToRender["IndependentDataName2"] = self.dataObject.IndependentDataName2
        itemsToRender["loadavg"] = platform_compat.get_loadavg()

        result_html_path = page_artifact_path(self.dataObject.uniqueString, "html")

        # File write and session save are intentionally separate try
        # blocks. Earlier this lived in one combined try, but a session
        # save failure (SQLite lock-retry budget exhausted) would then
        # enter the except branch and re-open result_html_path in 'w'
        # mode, truncating the just-written valid results file.
        write_succeeded = False
        try:
            with open(result_html_path, "w", encoding="utf-8") as f:
                f.write(
                    render_to_string(
                        "zunzun/equation_fit_or_characterizer_results.html", itemsToRender
                    )
                )
            write_succeeded = True
        except Exception:
            import logging

            logging.exception("Exception rendering HTML to a file")

            # Fallback 1: render the project's generic error template.
            # Most common failure mode (template change in the success
            # results template) doesn't affect this one.
            try:
                with open(result_html_path, "w", encoding="utf-8") as f:
                    f.write(
                        render_to_string(
                            "zunzun/generic_error.html",
                            {
                                "error": "An internal error occurred while generating "
                                "the results page."
                            },
                        )
                    )
                write_succeeded = True
            except Exception:
                logging.exception("Also failed to write generic error HTML; trying static fallback")

                # Fallback 2: a hardcoded HTML string that does not
                # depend on Django templates at all. Only fails if
                # disk itself is unwritable. Guarantees the polling
                # UI terminates whenever the disk works.
                try:
                    with open(result_html_path, "w", encoding="utf-8") as f:
                        f.write(
                            "<html><head><title>ZunZunNG - Error</title></head>"
                            "<body><h2>Error</h2>"
                            "<p>An internal error occurred while generating the results "
                            "page. Please try again or contact the administrator.</p>"
                            "</body></html>"
                        )
                    write_succeeded = True
                except Exception:
                    logging.exception("Also failed to write static fallback HTML")

        if write_succeeded:
            # Success terminal. Mark completed here too (belt-and-suspenders
            # with PerformAllWork's end-of-try process_id=0/completed=True
            # clear) so the gate's pending window can't re-fire after
            # StatusView consumes redirect_to_results.
            self.update_status(redirect_to_results=result_html_path, completed=True)
        else:
            # Disk is unwritable; we cannot deliver a terminal page.
            # Update status text so polling at least surfaces the error,
            # even though the page will not finalize.
            self.update_status(
                current_status="An internal error occurred while generating the "
                "results page. Please try again or contact the administrator."
            )

    def CreateUnboundInterfaceForm(self, request):  # OVERRIDDEN in fittingBaseClass
        dictionaryToReturn = {}
        dictionaryToReturn["dimensionality"] = str(self.dimensionality)

        dictionaryToReturn["header_text"] = "ZunZunNG"
        dictionaryToReturn["subtitle_text"] = (
            str(self.dimensionality) + "D Interface<br>" + self.webFormName
        )
        dictionaryToReturn["title_string"] = (
            "ZunZunNG " + str(self.dimensionality) + "D Interface " + self.webFormName
        )

        # make a dimensionality-based unbound Django form
        self.unboundForm = getattr(
            zunzun.forms, "CharacterizeDataForm_" + str(self.dimensionality) + "D"
        )()

        # set the form to have either default or session text data
        temp = self.LoadItemFromSessionStore(
            "data", "textDataEditor_" + str(self.dimensionality) + "D"
        )
        if temp:
            self.unboundForm.fields["textDataEditor"].initial = temp
        else:
            self.unboundForm.fields["textDataEditor"].initial = (
                zunzun.forms.formConstants.initialDataEntryText
                + getattr(self, "defaultData" + str(self.dimensionality) + "D")
            )
        temp = self.LoadItemFromSessionStore("data", "commaConversion")
        if temp:
            self.unboundForm.fields["commaConversion"].initial = temp
        self.unboundForm.weightedFittingPossibleFlag = (
            0  # weightedFittingChoice not used in characterizers
        )
        dictionaryToReturn["mainForm"] = self.unboundForm

        dictionaryToReturn["statisticalDistributions"] = self.statisticalDistribution

        return dictionaryToReturn

    def CreateBoundInterfaceForm(self, request):  # OVERRIDDEN in fittingBaseClass
        self.boundForm = getattr(
            zunzun.forms, "CharacterizeDataForm_" + str(self.dimensionality) + "D"
        )(request.POST)
        self.boundForm.dimensionality = str(self.dimensionality)
        self.boundForm["statisticalDistributionsSortBy"].required = self.statisticalDistribution
