import os, sys, copy, urllib.request, urllib.parse, urllib.error

import settings
from django.template.loader import render_to_string

from . import FittingBaseClass
from . import ReportsAndGraphs
from .child_payload import ChildPayload
import pyeq3

from . import pid_trace


class FunctionFinderResults(FittingBaseClass.FittingBaseClass):

    def __init__(self):
        super().__init__()
        self.equationName = None
        self.userInterfaceRequired = False
        self.equationDataForDjangoTemplate = []
        self.webFormName = 'Function Finder Results'
        self.reniceLevel = 11
        self.maxNumberOfEquationsToDisplay = 40
    
    
    def build_child_payload(self):
        payload = super().build_child_payload()
        # self.rank is set by the view dispatcher (LRP.rank = rank) before
        # build_child_payload is called; carry it into the child.
        payload.extra["rank"] = self.rank
        return payload

    def apply_child_payload(self, payload):
        super().apply_child_payload(payload)
        self.rank = payload.extra["rank"]

    def TransferFormDataToDataObject(self, request): # return any error in a user-viewable string (self.dataObject.ErrorString)
        IndependentDataName1 = self.LoadItemFromSessionStore('data', 'IndependentDataName1')
        IndependentDataName2 =self.LoadItemFromSessionStore('data', 'IndependentDataName2')
        DependentDataName = self.LoadItemFromSessionStore('data', 'DependentDataName')
        self.dataObject = self.BaseCreateAndInitializeDataObject(IndependentDataName1, IndependentDataName2, DependentDataName) 
        self.dataObject.commaConversion = self.LoadItemFromSessionStore('data', 'commaConversion')
        self.dataObject.equation = pyeq3.IModel.IModel()
        self.dataObject.equation._dimensionality = self.dimensionality

        self.functionFinderResultsList = self.LoadItemFromSessionStore('functionfinder', 'functionFinderResultsList')
        if self.functionFinderResultsList == None:
            return "Your session has expired.  Please run the function finder again."
        if self.functionFinderResultsList == []:
            return "No functions were found to model your data."

        self.dataObject.textDataEditor = self.LoadItemFromSessionStore('data', 'textDataEditor')
        self.dataObject.weightedFittingChoice = self.LoadItemFromSessionStore('data', 'weightedFittingChoice')
        self.dataObject.fittingTarget = self.LoadItemFromSessionStore('data', 'fittingTarget')
        self.dataObject.DependentDataArray = self.LoadItemFromSessionStore('data', 'DependentDataArray')
        self.dataObject.IndependentDataArray = self.LoadItemFromSessionStore('data', 'IndependentDataArray')

        self.dataObject.logLinX = self.LoadItemFromSessionStore('data', 'logLinX')
        self.dataObject.logLinY = self.LoadItemFromSessionStore('data', 'logLinY')

        if len(self.functionFinderResultsList) < self.rank:
            self.rank = len(self.functionFinderResultsList)

        self.numberOfEquationsToDisplay = len(self.functionFinderResultsList) - self.rank + 1
        if self.numberOfEquationsToDisplay > self.maxNumberOfEquationsToDisplay:
            self.numberOfEquationsToDisplay = self.maxNumberOfEquationsToDisplay

        # this is for determining 'previous' and 'next' links on page - use zero for "none"
        if self.rank == 1:
            self.previousSelectorRank = 0 # no 'previous' rank to go back to
        else:
            self.previousSelectorRank = self.rank - self.maxNumberOfEquationsToDisplay
            if self.previousSelectorRank < 1:
                self.previousSelectorRank = 0
        if self.rank > (len(self.functionFinderResultsList) - self.maxNumberOfEquationsToDisplay):
            self.nextSelectorRank = 0 # no 'next' rank to go forwards to
        else:
            self.nextSelectorRank = self.rank + self.maxNumberOfEquationsToDisplay
            if self.nextSelectorRank > len(self.functionFinderResultsList):
                self.nextSelectorRank = 0
        return ''

        
    def RenderOutputHTMLToAFileAndSetStatusRedirect(self):
        
        import time # acts strangely if import is at top of file
        
        self.SaveDictionaryOfItemsToSessionStore('status', {'currentStatus':"Generating Output HTML"})

        itemsToRender = {}
        itemsToRender['dimensionality'] = str(self.dataObject.dimensionality)
        itemsToRender['header_text'] = 'ZunZunSite3<br>' + str(self.dataObject.dimensionality) + 'D ' + self.webFormName
        itemsToRender['title_string'] = 'ZunZunSite3 ' + str(self.dataObject.dimensionality) + 'D ' + self.webFormName
        itemsToRender['equationDataForDjangoTemplate'] = self.equationDataForDjangoTemplate
        itemsToRender['uniqueTime'] = str(time.time())
        itemsToRender['previousSelectorRank'] = self.previousSelectorRank
        itemsToRender['nextSelectorRank'] = self.nextSelectorRank
        itemsToRender['RelativeErrorPlotsFlag'] = self.RelativeErrorPlotsFlag

        tempString = render_to_string('zunzun/function_finder_results.html', itemsToRender)
        fileLocation = os.path.join(settings.TEMP_FILES_DIR, self.dataObject.uniqueString + ".html")
        open(fileLocation, "w").write(tempString)
        self.SaveDictionaryOfItemsToSessionStore('status', {'redirectToResultsFileOrURL':fileLocation})
        

    def SetInitialStatusDataIntoSessionVariables(self, request):
        import time
        pid_trace.pid_trace()
        self.SaveDictionaryOfItemsToSessionStore('status',
                                                 {'currentStatus':'Initializing Reports and Graphs',
                                                  'start_time':time.time(),
                                                  'time_of_last_status_check':time.time(),
                                                  'redirectToResultsFileOrURL':''})
        pid_trace.delete_pid_trace_file()


    def GenerateListOfOutputReports(self):

        pid_trace.pid_trace()
        
        self.textReports = []
        self.graphReports = []

        externalDataCache = pyeq3.dataCache() # reuse this to speed up some caching
        
        for i in range(self.numberOfEquationsToDisplay):
            
            listItem = self.functionFinderResultsList[i + self.rank-1]

            reportDataObject = copy.copy(self.dataObject) 

            # find the equation instance for the incoming dimensionality, equation family name and equation name - 404 if not found
            reportDataObject.equation = eval(listItem[1] + "." + listItem[2] + "('SSQABS', '" + listItem[3] + "')")

            if externalDataCache.allDataCacheDictionary == {}: # This should only run for the first equation
                temp = reportDataObject.textDataEditor
                
                # comma conversions
                if reportDataObject.commaConversion == "D": # decimal separator
                    temp = temp.replace(",",".")
                elif reportDataObject.commaConversion == "I": # as if they don't exist
                    temp = temp.replace(",","")
                else:
                    temp = temp.replace(","," ") # default to the original default conversion
        
                # replace these characters with spaces for use by float()
                temp = temp.replace("$"," ")
                temp = temp.replace("%"," ")
                temp = temp.replace("("," ")
                temp = temp.replace(")"," ")
                temp = temp.replace("{"," ")
                temp = temp.replace("}"," ")
        
                temp = temp.replace('\r\n','\n')
                temp = temp.replace('\r','\n')
                
                # replace HTML spaces and tabs with spaces
                temp = temp.replace("&nbsp;"," ")
                temp = temp.replace("&#9;"," ")
                temp = temp.replace("&#09;"," ")
                temp = temp.replace("&#32;"," ")
                
                pyeq3.dataConvertorService().ConvertAndSortColumnarASCII(temp, reportDataObject.equation, False)
                externalDataCache = reportDataObject.equation.dataCache

            reportDataObject.equation.polyfunctional2DFlags = listItem[4]
            reportDataObject.equation.polyfunctional3DFlags = listItem[5]
            reportDataObject.equation.xPolynomialOrder = listItem[6]
            reportDataObject.equation.yPolynomialOrder = listItem[7]
            reportDataObject.equation.rationalNumeratorFlags = listItem[8]
            reportDataObject.equation.rationalDenominatorFlags = listItem[9]
            reportDataObject.equation.fittingTarget = listItem[10]
            reportDataObject.equation.solvedCoefficients = listItem[11]
             
            targetValue = listItem[0]
            
            reportDataObject.equation.dataCache = externalDataCache
            reportDataObject.equation.dataCache.FindOrCreateAllDataCache(reportDataObject.equation)
            externalDataCache = reportDataObject.equation.dataCache

            
            # add a bit more extrapolation for the function finder result displays
            reportDataObject.Extrapolation_x = 0.05
            reportDataObject.Extrapolation_y = 0.05
            reportDataObject.Extrapolation_z = 0.05
    
            # needed here for graph boundary calculation
            reportDataObject.graphWidth  = 280
            reportDataObject.graphHeight = 240
        
            # 3D rotation angles
            reportDataObject.altimuth3D = 45.0
            reportDataObject.azimuth3D  = 45.0
    
            reportDataObject.CalculateDataStatistics()
            reportDataObject.CalculateErrorStatistics()
            reportDataObject.CalculateGraphBoundaries()
            reportDataObject.equation.CalculateCoefficientAndFitStatistics()
    
            graphs = []
            # Different graphs for 2D and 3D
            reportDataObject.pngOnlyFlag = True
            if reportDataObject.equation.GetDimensionality() == 2:
                graph = ReportsAndGraphs.DependentDataVsIndependentData1_ModelPlot(reportDataObject)
                graph.rank = i + self.rank
                graph.PrepareForReportOutput()
                self.graphReports.append(graph)
                graphs.append(graph.websiteFileLocation)
            else:
                reportDataObject.dataPointSize3D = 1.0
                graph = ReportsAndGraphs.SurfacePlot(reportDataObject)
                graph.rank = i + self.rank
                graph.PrepareForReportOutput()
                self.graphReports.append(graph)
                graphs.append(graph.websiteFileLocation)
    
                graph = ReportsAndGraphs.ContourPlot(reportDataObject)
                graph.rank = i + self.rank
                graph.PrepareForReportOutput()
                graphs.append(graph.websiteFileLocation)
                self.graphReports.append(graph)
    
            if reportDataObject.equation.fittingTarget[-3:] != "REL":
                graph = ReportsAndGraphs.AbsoluteErrorVsDependentData_ScatterPlot(reportDataObject)
                graph.rank = i + self.rank
                graph.PrepareForReportOutput()
                self.graphReports.append(graph)
                graphs.append(graph.websiteFileLocation)
            else:
                graph = ReportsAndGraphs.RelativeErrorVsDependentData_ScatterPlot(reportDataObject)
                graph.rank = i + self.rank
                graph.PrepareForReportOutput()
                graphs.append(graph.websiteFileLocation)
                self.graphReports.append(graph)
    
            dataForOneEquation = {}
            splitted = listItem[1].split('.')
            dataForOneEquation['moduleName'] = splitted[-1]
            dataForOneEquation['displayName'] = reportDataObject.equation.GetDisplayName()
            dataForOneEquation['URLQuotedModuleName'] = urllib.parse.quote(splitted[-1])
            dataForOneEquation['URLQuotedDisplayName'] = urllib.parse.quote(reportDataObject.equation.GetDisplayName())
            dataForOneEquation['displayHTML'] = reportDataObject.equation.GetDisplayHTML()
            dataForOneEquation['graphWebSiteLocations'] = graphs
            dataForOneEquation['rank'] = i + self.rank
            dataForOneEquation['dimensionality'] = self.dimensionality
            dataForOneEquation['fittingTarget'] = reportDataObject.equation.fittingTarget
            dataForOneEquation['fittingTargetValue'] = targetValue
            if reportDataObject.fittingTarget[-3:] != "REL": # only non-relative error fits get these displayed
                dataForOneEquation['rmseString'] = '<br>RMSE: ' + str(reportDataObject.equation.rmse)
                dataForOneEquation['rsquaredString'] = '<br>R-squared: ' + str(reportDataObject.equation.r2) + '<br>'
                self.RelativeErrorPlotsFlag = False # ok to set many times
            else:
                dataForOneEquation['rmseString'] = '<br>'
                dataForOneEquation['rsquaredString'] = '<br>'
                self.RelativeErrorPlotsFlag = True # ok to set many times
            self.equationDataForDjangoTemplate.append(dataForOneEquation)
        
        pid_trace.pid_trace()

        
    def GenerateListOfWorkItems(self):
        pass

    
    def CreateReportPDF(self):
        pass # no PDF file

