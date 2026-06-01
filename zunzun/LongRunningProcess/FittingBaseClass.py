import inspect
import os
import sys

import numpy
import pyeq3
from django.template.loader import render_to_string

import settings
import zunzun.formConstants

from . import StatusMonitoredLongRunningProcessPage
from ._unique import page_artifact_path
from .StatusMonitoredLongRunningProcessPage import _ReportsPipelineAborted


class FittingBaseClass(StatusMonitoredLongRunningProcessPage.StatusMonitoredLongRunningProcessPage):
    extraExampleDataTextForWeightedFitting = """Weighted fitting requires an additional number to be used as a weight when fitting. The site does not calculate any weights, which are used as:

error = weight * (predicted - actual)

You must provide any weights you wish to use.

"""

    rank = None

    def build_child_payload(self):
        payload = super().build_child_payload()
        # Fit subclasses always have a bound equation via boundForm
        if self.boundForm is not None:
            payload.equation = self.boundForm.equation
        # pdfTitleHTML and webFormName are set during TransferFormDataToDataObject
        # in the parent (against self, not self.dataObject). The child's fresh
        # LRP instance doesn't have them; carry them explicitly.
        payload.extra["pdfTitleHTML"] = getattr(self, "pdfTitleHTML", "")
        payload.extra["webFormName"] = getattr(self, "webFormName", "")
        # equationInstance is set in CreateBoundInterfaceForm (parent) and
        # used by the results template to decide whether to show the
        # "Coefficients And Text Reports" and "Statistical Scatterplots"
        # dropdowns. Default in __init__ is 0 (falsy); without explicit
        # transport the child would render the results page as if no
        # equation were bound, dropping both sections.
        payload.extra["equationInstance"] = getattr(self, "equationInstance", 0)
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.pdfTitleHTML = payload.extra.get("pdfTitleHTML", "")
        self.webFormName = payload.extra.get("webFormName", "")
        self.equationInstance = payload.extra.get("equationInstance", 0)
        # In the child, there is no request and no boundForm — the
        # equation comes directly from the payload.
        self.equationFromPayload = payload.equation

    def _build_2d_color_list(self, selected_predicate):
        """Build the 2D coefficient-picker color list.

        Each entry is (selected, i, html); ``i`` indexes ``self.X2DList``.
        Unlike the 3D grid there is no offset special-case — every cell carries
        its term's HTML, including index 0. ``selected_predicate(i)`` returns the
        leading bool — pass ``lambda i: i in flags`` for a FunctionFinder rank
        pre-fill, or ``lambda i: False`` when not arriving from a function finder.
        The caller assigns the result into its own dictionary key
        (``Polyfun2DColorList`` vs ``Polynomial2DColorList``).
        """
        return [(selected_predicate(i), i, self.X2DList[i].HTML) for i in range(len(self.X2DList))]

    def _build_3d_color_list(self, selected_predicate):
        """Build the 3D coefficient-picker color list.

        Each entry is (selected, i, j, htmlX, htmlY). ``i`` indexes
        ``self.X3DList`` (row); ``j`` indexes ``self.Y3DList`` (column). The
        (0, 0) cell is the
        offset term; cells on the i==0 or j==0 axes carry only the other axis's
        HTML. ``selected_predicate(i, j)`` returns the leading bool — pass
        ``lambda i, j: [i, j] in flags`` for a FunctionFinder rank pre-fill, or
        ``lambda i, j: False`` when not arriving from a function finder.
        """
        color_list = []
        for i in range(len(self.X3DList)):
            for j in range(len(self.Y3DList)):
                selected = selected_predicate(i, j)
                if i == 0 and j == 0:
                    color_list.append((selected, i, j, "Offset", ""))
                elif i > 0 and j == 0:
                    color_list.append((selected, i, j, self.X3DList[i].HTML, ""))
                elif i == 0 and j > 0:
                    color_list.append((selected, i, j, "", self.Y3DList[j].HTML))
                else:
                    color_list.append((selected, i, j, self.X3DList[i].HTML, self.Y3DList[j].HTML))
        return color_list

    def _assign_2d_picker_color_list(self, key, equation_flag_attr):
        """Rank-aware 2D coefficient-picker color list -> dictionaryToReturn[key].

        On the FunctionFinder rank path, pre-fill selections from result-tuple
        index [4] and mirror them onto the equation's <equation_flag_attr>;
        otherwise no cell is pre-selected. Shared by the polyfunctional and
        customizable-polynomial 2D pickers, which differ only in
        (key, equation_flag_attr).
        """
        if self.rank:
            flags = self.functionFinderResultsList[self.rank - 1][4]
            setattr(self.equation, equation_flag_attr, flags)
            self.dictionaryToReturn[key] = self._build_2d_color_list(lambda i: i in flags)
        else:
            self.dictionaryToReturn[key] = self._build_2d_color_list(lambda i: False)

    def _assign_3d_picker_color_list(self, key, equation_flag_attr):
        """Rank-aware 3D coefficient-picker color list -> dictionaryToReturn[key].

        3D result-tuple index is [5]; flags are [i, j] pairs. Only the
        polyfunctional picker is 3D-capable, so only it calls this.
        """
        if self.rank:
            flags = self.functionFinderResultsList[self.rank - 1][5]
            setattr(self.equation, equation_flag_attr, flags)
            self.dictionaryToReturn[key] = self._build_3d_color_list(lambda i, j: [i, j] in flags)
        else:
            self.dictionaryToReturn[key] = self._build_3d_color_list(lambda i, j: False)

    def _collect_2d_picker_flags(self, request, equation_flag_attr):
        """Read 2D picker checkbox POST values into the bound equation's
        <equation_flag_attr> list, forcing field validation on each cell input."""
        flags = []
        for i in range(len(self.X2DList)):
            field = "polyFunctional_X" + str(i)
            self.boundForm[field].required = True
            if request.POST[field] == "True":
                flags.append(i)
        setattr(self.boundForm.equation, equation_flag_attr, flags)

    def _collect_3d_picker_flags(self, request, equation_flag_attr):
        """3D analogue of _collect_2d_picker_flags: cell ids are
        polyFunctional_X<i>Y<j> and flags are [i, j] pairs."""
        flags = []
        for i in range(len(self.X3DList)):
            for j in range(len(self.Y3DList)):
                field = "polyFunctional_X" + str(i) + "Y" + str(j)
                self.boundForm[field].required = True
                if request.POST[field] == "True":
                    flags.append([i, j])
        setattr(self.boundForm.equation, equation_flag_attr, flags)

    def CheckDataForZeroAndPositiveAndNegative(self):
        # check for zero
        if (
            self.boundForm.equation.independentData1CannotContainZeroFlag
            and self.boundForm.equation.dataCache.independentData1ContainsZeroFlag
        ):
            return (
                'This equation requires that "'
                + self.boundForm.cleaned_data["dataNameX"]
                + '" contain no zero values, but it contains at least one zero value.'
            )
        if (
            self.boundForm.equation.independentData2CannotContainZeroFlag
            and self.boundForm.equation.dataCache.independentData2ContainsZeroFlag
        ):
            return (
                'This equation requires that "'
                + self.boundForm.cleaned_data["dataNameY"]
                + '" contain no zero values, but it contains at least one zero value.'
            )

        # check for positive
        if (
            self.boundForm.equation.independentData1CannotContainPositiveFlag
            and self.boundForm.equation.dataCache.independentData1ContainsPositiveFlag
        ):
            return (
                'This equation requires that "'
                + self.boundForm.cleaned_data["dataNameX"]
                + '" contain no positive values, but it contains at least one positive value.'
            )
        if (
            self.boundForm.equation.independentData2CannotContainPositiveFlag
            and self.boundForm.equation.dataCache.independentData2ContainsPositiveFlag
        ):
            return (
                'This equation requires that "'
                + self.boundForm.cleaned_data["dataNameY"]
                + '" contain no positive values, but it contains at least one positive value.'
            )

        # check for negative
        if (
            self.boundForm.equation.independentData1CannotContainNegativeFlag
            and self.boundForm.equation.dataCache.independentData1ContainsNegativeFlag
        ):
            return (
                'This equation requires that "'
                + self.boundForm.cleaned_data["dataNameX"]
                + '" contain no negative values, but it contains at least one negative value.'
            )
        if (
            self.boundForm.equation.independentData2CannotContainNegativeFlag
            and self.boundForm.equation.dataCache.independentData2ContainsNegativeFlag
        ):
            return (
                'This equation requires that "'
                + self.boundForm.cleaned_data["dataNameY"]
                + '" contain no negative values, but it contains at least one negative value.'
            )

        # all good
        return ""

    def TransferFormDataToDataObject(
        self, request
    ):  # return any error in a user-viewable string (self.dataObject.ErrorString)
        self.CommonCreateAndInitializeDataObject(False)
        self.dataObject.textDataEditor = self.boundForm.cleaned_data["textDataEditor"]

        self.webFormName = (
            self.boundForm.equation.GetDisplayName()
            + " "
            + str(self.dimensionality)
            + 'D<br><span class="math">'
            + self.boundForm.equation.GetDisplayHTML()
            + "</span>"
        )  # requires the above call to Initalize()

        self.pdfTitleHTML = (
            "Equation Family: "
            + self.boundForm.equation.__module__.split(".")[-1]
            + "<br><br><br><br>"
        )
        self.pdfTitleHTML += (
            '<font name="LMRoman10" size="14">'
            + self.boundForm.equation.GetDisplayHTML()
            + "</font>"
        )  # requires the above webFormName which needs Initialize()

        self.boundForm.equation.dataCache = self.boundForm.equationBase.dataCache

        self.boundForm.equation.upperCoefficientBounds = self.boundForm.cleaned_data[
            "upperCoefficientBoundsList"
        ]
        self.boundForm.equation.lowerCoefficientBounds = self.boundForm.cleaned_data[
            "lowerCoefficientBoundsList"
        ]

        self.boundForm.equation.fixedCoefficients = self.boundForm.cleaned_data[
            "fixedCoefficientList"
        ]

        # Keep estimatedCoefficients as a Python list when empty, and only
        # promote to numpy.array when it holds values. pyeq3's SolverService
        # checks `if inModel.estimatedCoefficients != []:` — under modern
        # numpy (>=1.25), `numpy.array([]) != []` produces an empty bool
        # array and `if` on that raises "The truth value of an empty array
        # is ambiguous". A plain list [] avoids the ambiguous comparison.
        _estimates = self.boundForm.cleaned_data["estimatedCoefficientList"]
        try:
            n_coeffs = len(self.boundForm.equation.GetCoefficientDesignators())
            if len(_estimates) > n_coeffs:
                _estimates = _estimates[:n_coeffs]
        except Exception:
            _estimates = []
        self.boundForm.equation.estimatedCoefficients = (
            numpy.array(_estimates) if len(_estimates) > 0 else []
        )

        # estimates for each coefficients were not supplied
        for i in range(len(self.boundForm.equation.estimatedCoefficients)):
            if self.boundForm.equation.estimatedCoefficients[i] is None:
                return "Estimates for each parameter were not supplied. Please go back and check esimated parameters."

        self.dataObject.equation = self.boundForm.equation

        return ""

    def CreateUnboundInterfaceForm(self, request):

        self.dictionaryToReturn = {}
        self.dictionaryToReturn["dimensionality"] = str(self.dimensionality)

        # make a dimensionality-based unbound Django form
        self.unboundForm = eval("zunzun.forms.Equation_" + str(self.dimensionality) + "D()")

        # FF - set "rank" variable if coming from the function finders, else set "rank" to None
        if "RANK" in list(request.GET.keys()):
            try:
                self.rank = int(request.GET["RANK"])
            except:
                raise Exception("Incorrect call to equation interface.")
            if self.rank < 1 or self.rank > 10000000:  # must be between 1 and 10 million
                raise Exception("Bad call to equation interface.")

            # bounds check
            self.functionFinderResultsList = self.LoadItemFromSessionStore(
                "functionfinder", "functionFinderResultsList"
            )
            if self.functionFinderResultsList == None:
                raise Exception(
                    "Your browser's session cookie appears to have expired, please run the function finder again."
                )
            if len(self.functionFinderResultsList) < self.rank:
                self.rank = len(self.functionFinderResultsList)

            if self.dimensionality == 2:
                self.unboundForm.fields["dataNameX"].initial = self.LoadItemFromSessionStore(
                    "data", "IndependentDataName1"
                )
                self.unboundForm.fields["dataNameY"].initial = self.LoadItemFromSessionStore(
                    "data", "DependentDataName"
                )
            else:
                self.unboundForm.fields["dataNameX"].initial = self.LoadItemFromSessionStore(
                    "data", "IndependentDataName1"
                )
                self.unboundForm.fields["dataNameY"].initial = self.LoadItemFromSessionStore(
                    "data", "IndependentDataName2"
                )
                self.unboundForm.fields["dataNameZ"].initial = self.LoadItemFromSessionStore(
                    "data", "DependentDataName"
                )

            self.unboundForm.fields["fittingTarget"].initial = self.LoadItemFromSessionStore(
                "data", "fittingTarget"
            )

        self.dictionaryToReturn["quotedEquationFamilyName"] = self.inEquationFamilyName
        self.dictionaryToReturn["quotedEquationName"] = self.inEquationName

        self.equation = self.GetEquationFromNameAndFamily(
            self.inEquationName,
            self.inEquationFamilyName,
            checkForSplinesAndUserDefinedFunctionsFlag=1,
        )
        if not self.equation:  # could not find a matching equation or spline
            raise Exception(
                "Could not find the equation "
                + self.inEquationName
                + " in the equation family "
                + self.inEquationFamilyName
                + "."
            )

        self.SpecificEquationUnboundInterfaceCode(request)

        self.dictionaryToReturn["equationInstance"] = self.equation

        # set the form to have either default or session text data
        temp = self.LoadItemFromSessionStore(
            "data", "textDataEditor_" + str(self.dimensionality) + "D"
        )
        if temp:
            self.unboundForm.fields["textDataEditor"].initial = temp
        elif self.equation.splineFlag:
            self.unboundForm.fields["textDataEditor"].initial += self.equation.exampleData
        else:
            self.unboundForm.fields["textDataEditor"].initial += (
                self.extraExampleDataTextForWeightedFitting + self.equation.exampleData
            )

        # set any remaining form items
        temp = self.LoadItemFromSessionStore("data", "commaConversion")
        if temp:
            self.unboundForm.fields["commaConversion"].initial = temp
        temp = self.LoadItemFromSessionStore("data", "weightedFittingChoice")
        if temp:
            self.unboundForm.fields["weightedFittingChoice"].initial = temp

        # equation instance is now in hand, make items necessary for user interface
        self.dictionaryToReturn["header_text"] = "ZunZunNG"
        self.dictionaryToReturn["subtitle_text"] = (
            "Fitting Interface For "
            + self.equation.GetDisplayName()
            + " "
            + str(self.dimensionality)
            + 'D<br><span class="math">'
            + self.equation.GetDisplayHTML()
            + "</span>"
        )
        self.dictionaryToReturn["title_string"] = (
            "ZunZunNG - " + self.equation.GetDisplayName() + " Fitting Interface"
        )

        self.unboundForm.weightedFittingPossibleFlag = not self.spline

        temp = self.LoadItemFromSessionStore("data", "udfEditor_" + str(self.dimensionality) + "D")
        if temp:
            self.unboundForm.fields["udfEditor"].initial = temp

        # for the fixed and estimated coefficient templates
        if (
            not self.equation.userSelectablePolyfunctionalFlag
            and not self.equation.userCustomizablePolynomialFlag
            and not self.equation.splineFlag
            and not self.equation.userDefinedFunctionFlag
        ):
            coefficientBoundsTemplateRequirement = []
            fixedCoefficientTemplateRequirement = []
            estimatedCoefficientTemplateRequirement = []

            if self.equation.userSelectablePolynomialFlag:
                if str(self.dimensionality) == "2":
                    for i in range(len(zunzun.formConstants.polynomialOrder2DChoices)):
                        coefficientBoundsTemplateRequirement.append(
                            [
                                self.equation.listOfAdditionalCoefficientDesignators[i],
                                eval('self.unboundForm["upperCoefficientBound' + str(i) + '"]'),
                                eval('self.unboundForm["lowerCoefficientBound' + str(i) + '"]'),
                            ]
                        )
                        fixedCoefficientTemplateRequirement.append(
                            [
                                self.equation.listOfAdditionalCoefficientDesignators[i],
                                eval('self.unboundForm["fixedCoefficient' + str(i) + '"]'),
                            ]
                        )
                        estimatedCoefficientTemplateRequirement.append(
                            [
                                self.equation.listOfAdditionalCoefficientDesignators[i],
                                eval('self.unboundForm["estimatedCoefficient' + str(i) + '"]'),
                            ]
                        )
                else:
                    pass  # not used for 3D polynomials
            else:
                coeffDesignatorList = self.equation.GetCoefficientDesignators()
                for i in range(len(coeffDesignatorList)):
                    coefficientBoundsTemplateRequirement.append(
                        [
                            coeffDesignatorList[i],
                            eval('self.unboundForm["upperCoefficientBound' + str(i) + '"]'),
                            eval('self.unboundForm["lowerCoefficientBound' + str(i) + '"]'),
                        ]
                    )
                    if self.equation.upperCoefficientBounds:
                        if self.equation.upperCoefficientBounds[i] != None:
                            exec(
                                'self.unboundForm.fields["upperCoefficientBound'
                                + str(i)
                                + '"].initial = '
                                + str(self.equation.upperCoefficientBounds[i])
                            )
                    if self.equation.lowerCoefficientBounds:
                        if self.equation.lowerCoefficientBounds[i] != None:
                            exec(
                                'self.unboundForm.fields["lowerCoefficientBound'
                                + str(i)
                                + '"].initial = '
                                + str(self.equation.lowerCoefficientBounds[i])
                            )
                    fixedCoefficientTemplateRequirement.append(
                        [
                            coeffDesignatorList[i],
                            eval('self.unboundForm["fixedCoefficient' + str(i) + '"]'),
                        ]
                    )
                    estimatedCoefficientTemplateRequirement.append(
                        [
                            coeffDesignatorList[i],
                            eval('self.unboundForm["estimatedCoefficient' + str(i) + '"]'),
                        ]
                    )

            self.dictionaryToReturn["coefficientBoundsTemplateRequirement"] = (
                coefficientBoundsTemplateRequirement
            )
            self.dictionaryToReturn["fixedCoefficientTemplateRequirement"] = (
                fixedCoefficientTemplateRequirement
            )
            self.dictionaryToReturn["estimatedCoefficientTemplateRequirement"] = (
                estimatedCoefficientTemplateRequirement
            )

        self.dictionaryToReturn["mainForm"] = self.unboundForm

        return self.dictionaryToReturn

    def SpecificEquationBoundInterfaceCode(self, request):
        pass

    def SpecificEquationUnboundInterfaceCode(self, request):
        self.dictionaryToReturn["equationHTML"] = (
            '<span class="math">' + self.equation.GetDisplayHTML() + "</span>"
        )

    def CreateBoundInterfaceForm(self, request):

        # make a dimensionality-based bound Django form
        self.boundForm = eval(
            "zunzun.forms.Equation_" + str(self.dimensionality) + "D(request.POST)"
        )
        self.boundForm.dimensionality = str(self.dimensionality)

        self.boundForm["fittingTarget"].required = True

        if (
            self.inEquationName == "User-Selectable Rational"
        ):  # this "with offset" portion of the name is not in the URL
            if "polyRational_OFFSET" in request.POST:
                if request.POST["polyRational_OFFSET"] == "True":
                    self.inEquationName = self.inEquationName + " With Offset"

        self.boundForm.equation = self.GetEquationFromNameAndFamily(
            self.inEquationName,
            self.inEquationFamilyName,
            checkForSplinesAndUserDefinedFunctionsFlag=1,
        )
        if not self.boundForm.equation:  # could not find a matching equation or spline
            raise Exception(
                "Could not find the equation "
                + self.inEquationName
                + " in the equation family "
                + self.inEquationFamilyName
                + "."
            )

        self.SpecificEquationBoundInterfaceCode(request)

        self.equationInstance = self.boundForm.equation

    def GenerateListOfWorkItems(self):

        self.update_status(current_status="Fitting Data")

        try:
            self.dataObject.equation.Solve()
        except:
            itemsToRender = {}
            itemsToRender["error0"] = str(sys.exc_info()[0])
            itemsToRender["error1"] = str(sys.exc_info()[1])
            error_html_path = page_artifact_path(self.dataObject.uniqueString, "html")
            # Write the error HTML with explicit utf-8 encoding via a
            # context manager. Without encoding, Windows defaults to
            # cp1252 and a non-ASCII character in the Solve() exception
            # message (e.g., a math symbol in a pyeq3 equation name
            # echoed in the traceback) would raise UnicodeEncodeError —
            # which would propagate past the raise _ReportsPipelineAborted()
            # below, so PerformAllWork's sentinel catch would miss it.
            with open(error_html_path, "w", encoding="utf-8") as f:
                f.write(
                    render_to_string(
                        "zunzun/exception_while_fitting_an_equation.html", itemsToRender
                    )
                )
            # Publish the Solve-specific error template (already rendered
            # above) directly to this dispatch's row, clearing the gate.
            self.mark_terminal(redirect=error_html_path or "")
            # Without this raise, PerformAllWork continues into
            # PerformWorkInParallel / report generation on an unsolved
            # equation, and RenderOutputHTMLToAFileAndSetStatusRedirect
            # would overwrite the error redirect with a path to a
            # (broken) results page.
            raise _ReportsPipelineAborted()

    def GetEquationFromNameAndFamily(
        self,
        inEquationName,
        inEquationFamilyName,
        checkForSplinesAndUserDefinedFunctionsFlag,
    ):

        equation = None
        if self.dimensionality == 2:  # 2D
            submodules = inspect.getmembers(pyeq3.Models_2D)
        else:
            submodules = inspect.getmembers(pyeq3.Models_3D)

        for submodule in submodules:
            if inspect.ismodule(submodule[1]):
                if submodule[0] != inEquationFamilyName:
                    continue
                for equationClass in inspect.getmembers(submodule[1]):
                    if inspect.isclass(equationClass[1]):
                        for (
                            extendedName
                        ) in pyeq3.ExtendedVersionHandlers.extendedVersionHandlerNameList:
                            try:
                                tempEquation = equationClass[1]("SSQABS", extendedName)
                                if tempEquation.GetDisplayName() == inEquationName:
                                    equation = tempEquation
                            except:
                                continue

        # not an equation, check for splines
        if not equation and checkForSplinesAndUserDefinedFunctionsFlag:
            if inEquationFamilyName == "Spline" and inEquationName == "Spline":
                if self.dimensionality == 2:  # 2D
                    equation = pyeq3.Models_2D.Spline.Spline()
                else:  # 3D
                    equation = pyeq3.Models_3D.Spline.Spline()
            if (
                inEquationFamilyName == "UserDefinedFunction"
                and inEquationName == "UserDefinedFunction"
            ):
                if self.dimensionality == 2:  # 2D
                    equation = pyeq3.Models_2D.UserDefinedFunction.UserDefinedFunction()
                else:  # 3D
                    equation = pyeq3.Models_3D.UserDefinedFunction.UserDefinedFunction()

        return equation
