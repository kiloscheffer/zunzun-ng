import concurrent.futures.process
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
from . import DataObject, DefaultData, ReportsAndGraphs, pid_trace
from ._unique import (
    new_unique_string,
    page_artifact_filename,
    page_artifact_path,
    page_artifact_url,
)
from .child_payload import ChildPayload


class _ReportsPipelineAborted(Exception):
    """Sentinel raised when a parallel phase failure must abort the rest of
    PerformAllWork (PDF generation, HTML rendering, redirect). Caught only
    by PerformAllWork itself; never propagates further."""


def _json_native(value):
    """Recursively coerce numpy types to plain Python primitives.

    Session storage uses Django's default JSONSerializer post-Phase-3,
    which cannot encode numpy scalars or arrays. Ranking tuples and
    coefficient arrays produced by pyeq3 contain numpy floats; cast
    them here at the write boundary before handing off to the session
    helpers.
    """
    import numpy

    if isinstance(value, numpy.ndarray):
        return value.tolist()
    if isinstance(value, numpy.generic):
        return value.item()
    if isinstance(value, dict):
        return {k: _json_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_native(v) for v in value]
    return value


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
            if -1 != str(eval("inReportObject.dataObject." + str(item))).find(
                "bound"
            ):  # internal python objects
                continue

            s += str(item) + ": " + str(eval("inReportObject.dataObject." + str(item))) + "\n\n"

        logging.basicConfig(
            filename=os.path.join(settings.TEMP_FILES_DIR, str(os.getpid()) + ".log"),
            level=logging.DEBUG,
        )
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

        logging.basicConfig(
            filename=os.path.join(settings.TEMP_FILES_DIR, str(os.getpid()) + ".log"),
            level=logging.DEBUG,
        )
        logging.exception("Exception characterizer output")

        s = "\n"
        for item in dir(inReportObject.dataObject):
            if -1 != str(item).find("__"):  # internal python objects
                continue
            if -1 != str(eval("inReportObject.dataObject." + str(item))).find(
                "bound"
            ):  # internal python objects
                continue

            s += str(item) + ": " + str(eval("inReportObject.dataObject." + str(item))) + "\n\n"

        logging.basicConfig(
            filename=os.path.join(settings.TEMP_FILES_DIR, str(os.getpid()) + ".log"),
            level=logging.DEBUG,
        )
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
        self.session_status = None
        self.session_functionfinder = None

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
            session_key_status=self.session_key_status,
            session_key_data=self.session_key_data,
            session_key_functionfinder=getattr(self, "session_key_functionfinder", ""),
            dimensionality=self.dimensionality,
            renice_level=self.reniceLevel,
            data_object=getattr(self, "dataObject", None),
            equation=None,  # overridden by fit subclasses
            # Stamped by SetInitialStatusDataIntoSessionVariables (run
            # in the parent moments before this build). The child uses
            # it as a dispatch identity to detect "newer fit replaced me"
            # races in its terminal-error handler. getattr fallback to
            # 0.0 covers paths that don't run SetInitial (none in current
            # tree, but defensive).
            dispatch_id=getattr(self, "dispatched_at", 0.0),
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
        self.session_key_status = payload.session_key_status
        self.session_key_data = payload.session_key_data
        self.session_key_functionfinder = payload.session_key_functionfinder
        self.dimensionality = payload.dimensionality
        self.reniceLevel = payload.renice_level
        self.dataObject = payload.data_object
        self.inEquationName = payload.extra.get("inEquationName", "")
        self.inEquationFamilyName = payload.extra.get("inEquationFamilyName", "")
        # Carry the dispatch identity into the child so the various
        # processID/dispatched_at clear sites can do an ownership check
        # against `session.dispatched_at == self.dispatched_at` before
        # clobbering the latter — a newer fit's SetInitial in the parent
        # can overwrite the session's dispatched_at while leaving an
        # older child's processID intact, and the old check
        # (pid-only) would then clear the newer fit's dispatch markers.
        self.dispatched_at = payload.dispatch_id

    def PerformWorkInParallel(self):
        pass

    def SaveSpecificDataToSessionStore(self):
        pass

    def GenerateListOfWorkItems(self):
        pass

    def CreateReportPDF(self):
        pid_trace.pid_trace()

        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Creating PDF Output File"}
        )
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

            logging.basicConfig(
                filename=os.path.join(settings.TEMP_FILES_DIR, str(os.getpid()) + ".log"),
                level=logging.DEBUG,
            )
            logging.exception("Exception creating PDF file")

            self.pdfFileName = ""  # empty string used as a flag
        pid_trace.delete_pid_trace_file()

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
        pid_trace.pid_trace()

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

        pid_trace.pid_trace()

        if self.dataObject.dimensionality == 2:
            self.dataObject.logLinX = self.boundForm.cleaned_data["logLinX"]
            self.dataObject.logLinY = self.boundForm.cleaned_data["logLinY"]

        if True == FF:  # function finder, return here
            return self.dataObject

        self.dataObject.graphWidth = int(self.boundForm.cleaned_data["graphSize"].split("x")[0])
        self.dataObject.graphHeight = int(self.boundForm.cleaned_data["graphSize"].split("x")[1])

        if self.dataObject.dimensionality > 1:
            pid_trace.pid_trace()
            self.dataObject.Extrapolation_x = self.boundForm.cleaned_data["graphScaleX"]
            self.dataObject.Extrapolation_x_min = self.boundForm.cleaned_data["minManualScaleX"]
            self.dataObject.Extrapolation_x_max = self.boundForm.cleaned_data["maxManualScaleX"]

            pid_trace.pid_trace()
            self.dataObject.ScientificNotationX = self.boundForm.cleaned_data["scientificNotationX"]
            self.dataObject.ScientificNotationY = self.boundForm.cleaned_data["scientificNotationY"]
            self.dataObject.Extrapolation_y = self.boundForm.cleaned_data["graphScaleY"]
            self.dataObject.Extrapolation_y_min = self.boundForm.cleaned_data["minManualScaleY"]
            self.dataObject.Extrapolation_y_max = self.boundForm.cleaned_data["maxManualScaleY"]

        if self.dataObject.dimensionality > 2:
            pid_trace.pid_trace()
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

        pid_trace.pid_trace()

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

        pid_trace.pid_trace()

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

        pid_trace.delete_pid_trace_file()

    def SaveDictionaryOfItemsToSessionStore(self, inSessionStoreName, inDictionary):
        pid_trace.pid_trace(inSessionStoreName)

        session = getattr(self, "session_" + inSessionStoreName)
        if session is None:
            pid_trace.pid_trace("No session in sessionstore, creating new session")
            session = SessionStore(getattr(self, "session_key_" + inSessionStoreName))

        pid_trace.pid_trace()

        for i in list(inDictionary.keys()):
            item = inDictionary[i]
            pid_trace.pid_trace(str(i) + " type: " + str(type(item)))
            # Store the raw value. Callers are responsible for producing
            # JSON-native values (no numpy scalars, sets, or datetime).
            session[i] = item
            pid_trace.pid_trace(str(i) + " saved to session")

        pid_trace.pid_trace()

        if inSessionStoreName == "status":
            session["timestamp"] = time.time()

        # sometimes database is momentarily locked, so retry on exception to mitigate
        s = session
        save_complete = False
        saveRetries = 0
        while not save_complete:
            try:
                s.save()
                save_complete = True
            except Exception as e:
                time.sleep(0.1)
                saveRetries += 1
                if saveRetries > 100:
                    raise e

        pid_trace.pid_trace()

        db.connections.close_all()
        close_old_connections()
        session = None

        pid_trace.delete_pid_trace_file()

    def LoadItemFromSessionStore(self, inSessionStoreName, inItemName):
        pid_trace.pid_trace()

        session = getattr(self, "session_" + inSessionStoreName)
        if session is None:
            session = SessionStore(getattr(self, "session_key_" + inSessionStoreName))
        try:
            returnItem = session[inItemName]
        except KeyError:
            returnItem = None
        db.connections.close_all()
        close_old_connections()
        session = None

        pid_trace.delete_pid_trace_file()

        return returnItem

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

            logging.basicConfig(
                filename=os.path.join(settings.TEMP_FILES_DIR, f"{os.getpid()}.log"),
                level=logging.DEBUG,
            )
            logging.exception("Could not compute terminal-error artifact path")
            return None

        try:
            with open(error_html_path, "w", encoding="utf-8") as f:
                f.write(render_to_string("zunzun/generic_error.html", {"error": error_message}))
            return error_html_path
        except Exception:
            import logging

            logging.basicConfig(
                filename=os.path.join(settings.TEMP_FILES_DIR, f"{os.getpid()}.log"),
                level=logging.DEBUG,
            )
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

    def _publish_terminal_error(self, *, html_path, status_dict=None):
        """Ownership-gated bundled terminal write: redirect + gate-clear
        in a single SaveDictionaryOfItemsToSessionStore call.

        Called by the abort sites after they've prepared their terminal
        HTML (either via _write_terminal_error_html for generic errors,
        or by rendering exception_while_fitting_an_equation.html for
        Solve/UDF failures). Bundles `processID: 0` and
        `dispatched_at: 0` automatically; the caller passes any
        additional keys (currentStatus, parallelProcessCount, etc.)
        via `status_dict`.

        If _we_own_status_slot() returns False, a newer dispatch has
        taken over and we leave the shared session alone — the file
        on disk is harmless. If html_path is None (disk-truly-unwritable
        case from _write_terminal_error_html), the redirect key is
        omitted but the gate-clear still ships so the next retry isn't
        gate-blocked.
        """
        if not self._we_own_status_slot():
            return
        payload = dict(status_dict or {})
        payload.setdefault("processID", 0)
        payload.setdefault("dispatched_at", 0)
        if html_path:
            payload["redirectToResultsFileOrURL"] = html_path
        self.SaveDictionaryOfItemsToSessionStore("status", payload)

    def _we_own_status_slot(self):
        """True iff this child still owns the shared status session.

        Dual identity check: both `processID` AND `dispatched_at` must
        match our own. processID alone is insufficient because a newer
        fit's SetInitialStatusDataIntoSessionVariables in the parent
        overwrites session.dispatched_at without touching processID;
        an older child clearing the slot on a pid-only match would
        clobber the newer fit's tracking.

        On transient session-read failure (Django's session backend
        wraps a SQLite read, which can raise OperationalError under
        lock contention or InterfaceError after close_old_connections),
        returns True. Letting a read hiccup return False would suppress
        the success redirect at RenderOutputHTMLToAFileAndSetStatusRedirect
        and re-introduce the stuck-poll bug this PR was built to fix.
        The fall-through is logged so postmortems can distinguish
        "correctly newer-fit-owned" from "ownership read failed."

        Used to gate every shared-session write — both failure/abort
        paths AND the success-redirect publish in
        RenderOutputHTMLToAFileAndSetStatusRedirect (overridden in
        FunctionFinder and FunctionFinderResults). AttributeError on
        self.dispatched_at (subclass that bypassed apply_child_payload)
        is NOT swallowed — that's a contract violation, not a transient
        read failure, and should propagate.
        """
        # Common transient-read exception classes from Django's session
        # backend wrapping SQLite. Imported locally to avoid pulling
        # them into module scope just for the except clause.
        from django.db import DatabaseError, InterfaceError

        try:
            return (
                self.LoadItemFromSessionStore("status", "processID") == os.getpid()
                and self.LoadItemFromSessionStore("status", "dispatched_at") == self.dispatched_at
            )
        except DatabaseError, InterfaceError:
            import logging

            logging.basicConfig(
                filename=os.path.join(settings.TEMP_FILES_DIR, f"{os.getpid()}.log"),
                level=logging.DEBUG,
            )
            logging.exception(
                "Ownership check session read failed; defaulting we-own=True "
                "(self.dispatched_at=%s os.getpid()=%s)",
                getattr(self, "dispatched_at", "<unset>"),
                os.getpid(),
            )
            return True

    def PerformAllWork(self):
        pid_trace.pid_trace()

        self.fit_pool = FitPool()
        try:
            self.SaveDictionaryOfItemsToSessionStore("status", {"processID": os.getpid()})

            pid_trace.pid_trace()

            self.GenerateListOfWorkItems()

            pid_trace.pid_trace()

            self.PerformWorkInParallel()

            pid_trace.pid_trace()

            self.GenerateListOfOutputReports()

            pid_trace.pid_trace()

            self.CreateOutputReportsInParallelUsingProcessPool()

            self.CreateReportPDF()

            pid_trace.pid_trace()

            self.RenderOutputHTMLToAFileAndSetStatusRedirect()

            # Clear processID AND dispatched_at so the per-user gate
            # (views.LongRunningProcessView) doesn't block this user's
            # next fit. The dual ownership check (_we_own_status_slot)
            # ensures we don't clobber a replacement fit's tracking
            # when ALLOW_MULTIPLE_CONCURRENT_FITS_PER_USER=True. Note:
            # every _ReportsPipelineAborted call site now bundles its
            # own dispatch-cleared status write before raising — this
            # success-path clear is symmetrical for the no-error case.
            # start_time is left intact because the status template
            # uses it for elapsed-time display.
            if self._we_own_status_slot():
                self.SaveDictionaryOfItemsToSessionStore(
                    "status", {"processID": 0, "dispatched_at": 0}
                )

            pid_trace.delete_pid_trace_file()
        except _ReportsPipelineAborted:
            # The reports phase wrote its own user-visible status AND
            # terminal redirect (via _publish_terminal_error /
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
            # scipy/numpy crash, session-store DB error). Clears ONLY
            # processID — NOT dispatched_at — because _run_fit_child's
            # except-branch ownership check uses session.dispatched_at
            # vs payload.dispatch_id to decide whether to publish a
            # terminal redirect. Wiping dispatched_at here would make
            # the ownership check see a mismatch on its OWN dispatch's
            # failure (our payload.dispatch_id != session 0), skip the
            # redirect write, and leave the polling UI stuck.
            # _run_fit_child's gate-clear step clears dispatched_at
            # after the ownership-verified redirect write, so the gate
            # is still released for the next user retry.
            # Conditional on still owning the pid avoids clobbering a
            # concurrent fit's tracking.
            try:
                if self.LoadItemFromSessionStore("status", "processID") == os.getpid():
                    self.SaveDictionaryOfItemsToSessionStore("status", {"processID": 0})
            except Exception:
                pass  # finally cleanup must not raise

    def CreateOutputReportsInParallelUsingProcessPool(self):
        pid_trace.pid_trace()

        self.SaveDictionaryOfItemsToSessionStore("status", {"currentStatus": "Running All Reports"})

        reportsToBeRunInParallel = self.graphReports + self.textReports
        totalNumberOfReportsToBeRun = len(reportsToBeRunInParallel)

        if totalNumberOfReportsToBeRun == 0:
            self.SaveDictionaryOfItemsToSessionStore("status", {"parallelProcessCount": 0})
            pid_trace.delete_pid_trace_file()
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

            logging.basicConfig(
                filename=os.path.join(settings.TEMP_FILES_DIR, f"{os.getpid()}.log"),
                level=logging.DEBUG,
            )
            logging.exception("BrokenProcessPool in CreateOutputReportsInParallelUsingProcessPool")
            # Publish terminal redirect + status text in one
            # ownership-gated atomic write so the polling UI completes
            # — PerformAllWork's `except _ReportsPipelineAborted: pass`
            # swallows the abort without propagating to _run_fit_child.
            error_message = (
                "An internal error occurred during report generation. "
                "Please try again or contact the administrator."
            )
            self._publish_terminal_error(
                html_path=self._write_terminal_error_html(error_message),
                status_dict={
                    "currentStatus": error_message,
                    "parallelProcessCount": 0,
                },
            )
            pid_trace.delete_pid_trace_file()
            raise _ReportsPipelineAborted()

        self.SaveDictionaryOfItemsToSessionStore("status", {"parallelProcessCount": 0})
        pid_trace.delete_pid_trace_file()

    def _oneSecondStatusUpdate(self, currentStatus):
        """Throttled (≤1Hz) liveness + status write for tight work loops.

        Per second: runs ``CheckIfStillUsed`` to detect abandoned fits,
        writes the supplied ``currentStatus`` plus the current
        ``parallelProcessCount`` to the status session, and bumps
        ``self.oneSecondTimes``. Returns immediately if a second hasn't
        elapsed since the last call.

        ``parallelProcessCount`` lives as its own session field so the
        status page renders it next to the elapsed timer instead of
        wedged into ``currentStatus``. UI hides the indicator when the
        count is ≤1 (single-thread phases or pool idle).

        Used by ``Reports_CheckOneSecondSessionUpdates`` here, and by
        the equivalent ``WorkItems_*`` methods on the FunctionFinder and
        StatisticalDistributions subclasses.
        """
        if self.oneSecondTimes == int(time.time()):
            return
        self.CheckIfStillUsed()
        self.SaveDictionaryOfItemsToSessionStore(
            "status",
            {
                "currentStatus": currentStatus,
                "parallelProcessCount": len(multiprocessing.active_children()),
            },
        )
        self.oneSecondTimes = int(time.time())

    def Reports_CheckOneSecondSessionUpdates(self, countOfReportsRun, totalNumberOfReportsToBeRun):
        self._oneSecondStatusUpdate(
            "Created %s of %s Reports and Graphs" % (countOfReportsRun, totalNumberOfReportsToBeRun)
        )

    def CheckIfStillUsed(self):
        import time

        if self.LoadItemFromSessionStore("status", "processID") is None:
            return

        # if a new process ID is in the session data, another process was started and this process was abandoned
        if (
            self.LoadItemFromSessionStore("status", "processID") != os.getpid()
            and self.LoadItemFromSessionStore("status", "processID") != 0
        ):
            time.sleep(1.0)

            pid_trace.pid_trace()

            if self.fit_pool is not None:
                self.fit_pool.shutdown(wait=False, cancel_futures=True)
                self.fit_pool = None
            # FunctionFinder's per-fit sub-pool, if present
            if getattr(self, "ff_pool", None) is not None:
                self.ff_pool.shutdown(wait=False, cancel_futures=True)
                self.ff_pool = None
            # shutdown(cancel_futures=True) only cancels PENDING futures;
            # workers currently executing a long pyeq3 fit continue until
            # their task completes. Terminate them immediately so an
            # abandoned fit doesn't keep consuming CPU/RAM.
            for p in multiprocessing.active_children():
                p.terminate()

            pid_trace.delete_pid_trace_file()

        # if the status has not been checked in the past 30 seconds, this process was abandoned
        if (
            time.time() - self.LoadItemFromSessionStore("status", "time_of_last_status_check")
        ) > 300:
            pid_trace.pid_trace()

            time.sleep(1.0)
            if self.fit_pool is not None:
                self.fit_pool.shutdown(wait=False, cancel_futures=True)
                self.fit_pool = None
            # FunctionFinder's per-fit sub-pool, if present
            if getattr(self, "ff_pool", None) is not None:
                self.ff_pool.shutdown(wait=False, cancel_futures=True)
                self.ff_pool = None
            # shutdown(cancel_futures=True) only cancels PENDING futures;
            # workers currently executing a long pyeq3 fit continue until
            # their task completes. Terminate them immediately so an
            # abandoned fit doesn't keep consuming CPU/RAM.
            for p in multiprocessing.active_children():
                p.terminate()

            pid_trace.delete_pid_trace_file()

    def SetInitialStatusDataIntoSessionVariables(self, request):
        pid_trace.pid_trace()
        # Compute the dispatch timestamp ONCE and store on self so
        # build_child_payload can stamp the same value into the payload.
        # The child uses payload.dispatch_id == session.dispatched_at as
        # an ownership identifier to detect "newer fit replaced me" races
        # in its terminal-error handler.
        self.dispatched_at = time.time()
        self.SaveDictionaryOfItemsToSessionStore(
            "status",
            {
                "currentStatus": "Initializing",
                "start_time": time.time(),
                "time_of_last_status_check": time.time(),
                "redirectToResultsFileOrURL": "",
                "parallelProcessCount": 0,
                "dispatched_at": self.dispatched_at,
            },
        )

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
        pid_trace.delete_pid_trace_file()

    def SpecificCodeForGeneratingListOfOutputReports(self):
        pid_trace.pid_trace()

        self.functionString = "PrepareForReportOutput"
        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Calculating Error Statistics"}
        )
        self.dataObject.CalculateErrorStatistics()

        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Calculating Parameter Statistics"}
        )
        self.dataObject.equation.CalculateCoefficientAndFitStatistics()

        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Generating Report Objects"}
        )
        self.ReportsAndGraphsCategoryDict = ReportsAndGraphs.FittingReportsDict(self.dataObject)

        pid_trace.delete_pid_trace_file()

    def GenerateListOfOutputReports(self):
        pid_trace.pid_trace()

        self.textReports = []
        self.graphReports = []

        # calculate data statistics and graph boundaries
        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Calculating Data Statistics"}
        )
        self.dataObject.CalculateDataStatistics()

        if self.dataObject.dimensionality > 1:
            self.SaveDictionaryOfItemsToSessionStore(
                "status", {"currentStatus": "Calculating Graph Boundaries"}
            )
            self.dataObject.CalculateGraphBoundaries()

        pid_trace.pid_trace()

        self.SpecificCodeForGeneratingListOfOutputReports()

        # generate required text reports
        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Generating List Of Text Reports"}
        )
        for i in self.ReportsAndGraphsCategoryDict["Text Reports"]:
            exec("i." + self.functionString + "()")
            if i.name != "":
                self.textReports.append(i)

        pid_trace.pid_trace()

        # select required graph reports
        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Generating List Of Graphical Reports"}
        )
        for i in self.ReportsAndGraphsCategoryDict["Graph Reports"]:
            exec("i." + self.functionString + "()")
            if i.name != "":
                self.graphReports.append(i)

        pid_trace.delete_pid_trace_file()

    def RenderOutputHTMLToAFileAndSetStatusRedirect(self):
        pid_trace.pid_trace()

        # Entry-gate: bail before any shared-session write if a newer
        # dispatch owns the slot. See `_we_own_status_slot` docstring
        # for the contract; the post-render disk artifact, if any,
        # would be unreferenced and is fine to skip.
        if not self._we_own_status_slot():
            import logging

            logging.basicConfig(
                filename=os.path.join(settings.TEMP_FILES_DIR, f"{os.getpid()}.log"),
                level=logging.DEBUG,
            )
            logging.info(
                "%s.RenderOutputHTML: newer dispatch owns slot; "
                "skipping shared-session writes (self.dispatched_at=%s)",
                type(self).__name__,
                self.dispatched_at,
            )
            return

        self.SaveSpecificDataToSessionStore()

        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Generating Output HTML"}
        )

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
            itemsToRender["EvaluateAtAPointForm"] = eval(
                "zunzun.forms.EvaluateAtAPointForm_" + str(self.dimensionality) + "D()"
            )
            itemsToRender["IndependentDataName1"] = self.dataObject.IndependentDataName1
            itemsToRender["IndependentDataName2"] = self.dataObject.IndependentDataName2
        itemsToRender["loadavg"] = platform_compat.get_loadavg()

        pid_trace.pid_trace()

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

            logging.basicConfig(
                filename=os.path.join(settings.TEMP_FILES_DIR, str(os.getpid()) + ".log"),
                level=logging.DEBUG,
            )
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

        # TOCTOU re-check before redirect publish; silent (entry-gate logs).
        if not self._we_own_status_slot():
            return

        if write_succeeded:
            self.SaveDictionaryOfItemsToSessionStore(
                "status", {"redirectToResultsFileOrURL": result_html_path}
            )
        else:
            # Disk is unwritable; we cannot deliver a terminal page.
            # Update status text so polling at least surfaces the error,
            # even though the page will not finalize.
            self.SaveDictionaryOfItemsToSessionStore(
                "status",
                {
                    "currentStatus": "An internal error occurred while generating the "
                    "results page. Please try again or contact the administrator."
                },
            )

        pid_trace.delete_pid_trace_file()

    def CreateUnboundInterfaceForm(self, request):  # OVERRIDDEN in fittingBaseClass
        pid_trace.pid_trace()
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
        self.unboundForm = eval(
            "zunzun.forms.CharacterizeDataForm_" + str(self.dimensionality) + "D()"
        )

        # set the form to have either default or session text data
        temp = self.LoadItemFromSessionStore(
            "data", "textDataEditor_" + str(self.dimensionality) + "D"
        )
        if temp:
            self.unboundForm.fields["textDataEditor"].initial = temp
        else:
            self.unboundForm.fields["textDataEditor"].initial = (
                zunzun.forms.formConstants.initialDataEntryText
                + eval("self.defaultData" + str(self.dimensionality) + "D")
            )
        temp = self.LoadItemFromSessionStore("data", "commaConversion")
        if temp:
            self.unboundForm.fields["commaConversion"].initial = temp
        self.unboundForm.weightedFittingPossibleFlag = (
            0  # weightedFittingChoice not used in characterizers
        )
        dictionaryToReturn["mainForm"] = self.unboundForm

        dictionaryToReturn["statisticalDistributions"] = self.statisticalDistribution

        pid_trace.delete_pid_trace_file()
        return dictionaryToReturn

    def CreateBoundInterfaceForm(self, request):  # OVERRIDDEN in fittingBaseClass
        pid_trace.pid_trace()
        self.boundForm = eval(
            "zunzun.forms.CharacterizeDataForm_" + str(self.dimensionality) + "D(request.POST)"
        )
        self.boundForm.dimensionality = str(self.dimensionality)
        self.boundForm["statisticalDistributionsSortBy"].required = self.statisticalDistribution
        pid_trace.delete_pid_trace_file()
