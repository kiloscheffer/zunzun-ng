import time

import zunzun.forms

from . import ReportsAndGraphs, StatusMonitoredLongRunningProcessPage
from .child_payload import ChildPayload


class CharacterizeData(StatusMonitoredLongRunningProcessPage.StatusMonitoredLongRunningProcessPage):
    def __init__(self):
        super().__init__()
        self.interfaceString = (
            "zunzun/characterize_data_or_statistical_distributions_interface.html"
        )
        self.equationName = None
        self.webFormName = "Data Characterization"
        self.characterizerOutputTrueOrReportOutputFalse = True
        self.evaluateAtAPointFormNeeded = False

    def build_child_payload(self):
        payload = super().build_child_payload()
        payload.extra["pdfTitleHTML"] = self.pdfTitleHTML
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.pdfTitleHTML = payload.extra["pdfTitleHTML"]

    def TransferFormDataToDataObject(
        self, request
    ):  # return any error in a user-viewable string (self.dataObject.ErrorString)
        self.pdfTitleHTML = self.webFormName + " " + str(self.dimensionality) + "D"
        self.CommonCreateAndInitializeDataObject(False)
        self.dataObject.equation = self.boundForm.equationBase
        self.dataObject.textDataEditor = self.boundForm.cleaned_data["textDataEditor"]

    def SpecificCodeForGeneratingListOfOutputReports(self):
        self.functionString = "PrepareForCharacterizerOutput"
        self.SaveDictionaryOfItemsToSessionStore(
            "status", {"currentStatus": "Generating Report Objects"}
        )
        self.ReportsAndGraphsCategoryDict = ReportsAndGraphs.CharacterizerReportsDict(
            self.dataObject
        )
