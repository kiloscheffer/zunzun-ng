import os, sys, time, math
from . import MatplotlibGraphs_2D
import numpy, scipy
import pyeq3
import uuid
import settings
from zunzun import platform_compat
from ._unique import b36

# matplotlib animation helpers for ScatterAnimation / SurfaceAnimation
from matplotlib.animation import FuncAnimation, PillowWriter

class Report(object):

    def __init__(self, dataObject):
        self.dataObject = dataObject
        self.stringList = []
        self.name= ''
        self.uuid = uuid.uuid4()

    def PrepareForReportOutput(self):
        self.PrepareForCharacterizerOutput()

    def PrepareForCharacterizerOutput(self):
        pass

    def CreateReportOutput(self):
        self.CreateCharacterizerOutput()

class TextOnlyReport(Report):

    def __init__(self, dataObject):
        Report.__init__(self, dataObject)

    def AddOneStatisticToStringList(self, label, selection, prefaceList):
        if prefaceList[0] + selection in self.dataObject.statistics:
            temp1 = '%- E' % self.dataObject.statistics[prefaceList[0] + selection]
            if len(temp1) < 13:
                temp1 += ' '
        else:
            temp1 = '&nbsp;    n/a      '
        if len(prefaceList) > 1 and prefaceList[1] + selection in self.dataObject.statistics:
            temp2 = '%- E' % self.dataObject.statistics[prefaceList[1] + selection]
            if len(temp2) < 13:
                temp2 += ' '
        else:
            temp2 = '&nbsp;    n/a      '
        if len(prefaceList) > 2 and  prefaceList[2] + selection in self.dataObject.statistics:
            temp3 = '%- E' % self.dataObject.statistics[prefaceList[2] + selection]
            if len(temp3) < 13:
                temp3 += ' '
        else:
            temp3 = '&nbsp;    n/a      '

        if len(prefaceList) == 1:
            self.stringList.append(label + temp1)
        if len(prefaceList) == 2:
            self.stringList.append(label + temp1 + '&nbsp;   ' + temp2)
        if len(prefaceList) == 3:
            self.stringList.append(label + temp1 + '&nbsp;   ' + temp2 + '&nbsp;   ' + temp3)

    def AddStatisticsToStringList(self, prefaceList):
        self.AddOneStatisticToStringList('Minimum:              ', '_min', prefaceList)
        self.AddOneStatisticToStringList('Maximum:              ', '_max', prefaceList)
        self.AddOneStatisticToStringList('Mean:                 ', '_mean', prefaceList)
        self.AddOneStatisticToStringList('Std. Error of Mean:   ', '_sem', prefaceList)
        self.AddOneStatisticToStringList('Median:               ', '_median', prefaceList)
        self.AddOneStatisticToStringList('Variance:             ', '_var', prefaceList)
        self.AddOneStatisticToStringList('Standard Deviation:   ', '_std', prefaceList)
        self.AddOneStatisticToStringList('Skew:                 ', '_skew', prefaceList)
        self.AddOneStatisticToStringList('Kurtosis:             ', '_kurtosis', prefaceList)

# enter in Text Reports at bottom
class CodeReportCPP(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.userDefinedFunctionFlag:
            self.name= ''
            return
        self.name = 'Source Code in C++'
        self.uniqueAnchorName = 'cpp'

    def CreateReportOutput(self):
        code = pyeq3.outputSourceCodeService().GetOutputSourceCodeCPP(self.dataObject.equation)
        self.stringList.append(code)

# enter in Text Reports at bottom
class CodeReportFORTRAN90(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.userDefinedFunctionFlag or self.dataObject.equation.splineFlag:
            self.name= ''
            return
        self.name = 'Source Code in Fortran90'
        self.uniqueAnchorName = 'f90'

    def CreateReportOutput(self):
        code = pyeq3.outputSourceCodeService().GetOutputSourceCodeFORTRAN90(self.dataObject.equation)
        self.stringList.append(code)

# enter in Text Reports at bottom
class CodeReportJAVA(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.userDefinedFunctionFlag:
            self.name= ''
            return
        self.name = 'Source Code in Java'
        self.uniqueAnchorName = 'jav'

    def CreateReportOutput(self):
        code = pyeq3.outputSourceCodeService().GetOutputSourceCodeJAVA(self.dataObject.equation)
        self.stringList.append(code)

# enter in Text Reports at bottom
class CodeReportJAVASCRIPT(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.userDefinedFunctionFlag:
            self.name= ''
            return
        self.name = 'Source Code in JavaScript'
        self.uniqueAnchorName = 'jsc'

    def CreateReportOutput(self):
        code = pyeq3.outputSourceCodeService().GetOutputSourceCodeJAVASCRIPT(self.dataObject.equation)
        self.stringList.append(code)

# enter in Text Reports at bottom
class CodeReportJULIA(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.userDefinedFunctionFlag or self.dataObject.equation.splineFlag:
            self.name= ''
            return
        self.name = 'Source Code in Julia'
        self.uniqueAnchorName = 'jul'

    def CreateReportOutput(self):
        code = pyeq3.outputSourceCodeService().GetOutputSourceCodeJULIA(self.dataObject.equation)
        self.stringList.append(code)

# enter in Text Reports at bottom
class CodeReportPYTHON(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.userDefinedFunctionFlag:
            self.name= ''
            return
        self.name = 'Source Code in Python'
        self.uniqueAnchorName = 'pyt'

    def CreateReportOutput(self):
        code = pyeq3.outputSourceCodeService().GetOutputSourceCodePYTHON(self.dataObject.equation)
        self.stringList.append(code)

# enter in Text Reports at bottom
class CodeReportCSHARP(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.userDefinedFunctionFlag or self.dataObject.equation.splineFlag:
            self.name= ''
            return
        self.name = 'Source Code in C#'
        self.uniqueAnchorName = 'csh'

    def CreateReportOutput(self):
        code = pyeq3.outputSourceCodeService().GetOutputSourceCodeCSHARP(self.dataObject.equation)
        self.stringList.append(code)

# enter in Text Reports at bottom
class CodeReportSCILAB(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.userDefinedFunctionFlag or self.dataObject.equation.splineFlag:
            self.name= ''
            return
        self.name = 'Source Code in SCILAB'
        self.uniqueAnchorName = 'sci'

    def CreateReportOutput(self):
        code = pyeq3.outputSourceCodeService().GetOutputSourceCodeSCILAB(self.dataObject.equation)
        self.stringList.append(code)

# enter in Text Reports at bottom
class CodeReportMATLAB(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.userDefinedFunctionFlag or self.dataObject.equation.splineFlag:
            self.name= ''
            return
        self.name = 'Source Code in MATLAB'
        self.uniqueAnchorName = 'mat'

    def CreateReportOutput(self):
        code = pyeq3.outputSourceCodeService().GetOutputSourceCodeMATLAB(self.dataObject.equation)
        self.stringList.append(code)

# enter in Text Reports at bottom
class CodeReportVBA(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.userDefinedFunctionFlag or self.dataObject.equation.splineFlag:
            self.name= ''
            return
        self.name = 'Source Code in VBA'
        self.uniqueAnchorName = 'vba'

    def CreateReportOutput(self):
        code = pyeq3.outputSourceCodeService().GetOutputSourceCodeVBA(self.dataObject.equation)
        self.stringList.append(code)

# enter in Text Reports at bottom
class UserDefinedFunctionText(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if not self.dataObject.equation.userDefinedFunctionFlag:
            self.name= ''
            return
        self.name = 'User Defined Function Text'
        self.uniqueAnchorName = 'udf'

    def CreateReportOutput(self):
        self.stringList.append(self.dataObject.equation.userDefinedFunctionText + '\n')

# enter in Text Reports at bottom
class CoefficientListing(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.splineFlag:
            self.name = 'Coefficients And Knot Points'
        else:
            self.name = 'Coefficients'
        self.uniqueAnchorName = 'cof'

    def CreateReportOutput(self):
        self.stringList.append(self.dataObject.equation.GetDisplayHTML() + '\n')

        if self.dataObject.equation.splineFlag:
            if self.dataObject.dimensionality == 2:
                coeffs = self.dataObject.equation.scipySpline._eval_args[1]
                xKnots = self.dataObject.equation.scipySpline._eval_args[0]
            else:
                coeffs = self.dataObject.equation.scipySpline.get_coeffs()
                xKnots = self.dataObject.equation.scipySpline.get_knots()[0]
                yKnots = self.dataObject.equation.scipySpline.get_knots()[1]
        else:
            coeffs = self.dataObject.equation.solvedCoefficients
            fittingTargetText = 'Fitting target of lowest ' + self.dataObject.equation.fittingTargetDictionary[self.dataObject.equation.fittingTarget]
            self.stringList.append(fittingTargetText + ' = %.16E' % (self.dataObject.equation.CalculateAllDataFittingTarget(self.dataObject.equation.solvedCoefficients)) + '\n')

        for i in range(len(coeffs)):
            if self.dataObject.equation.splineFlag:
                designator = 'coeff ' + str(i)
            else:
                designator = self.dataObject.equation.GetCoefficientDesignators()[i]
            if coeffs[i] < 0.0:
                self.stringList.append('%s = %-.16E' % (designator, coeffs[i]))
            else: # need a hard space if there is no negative sign
                self.stringList.append('%s =  %-.16E' % (designator, coeffs[i]))

        if self.dataObject.equation.splineFlag:
            self.stringList.append('<br>')
            if self.dataObject.dimensionality == 2:
                for i in range(len(xKnots)):
                    designator = 'knot point ' + str(i)
                    if xKnots[i] < 0.0:
                        self.stringList.append('%s = %-.16E' % (designator, xKnots[i]))
                    else: # need a hard space if there is no negative sign
                        self.stringList.append('%s =  %-.16E' % (designator, xKnots[i]))
            else:
                for i in range(len(xKnots)):
                    designator = 'X knot point ' + str(i)
                    if xKnots[i] < 0.0:
                        self.stringList.append('%s = %-.16E' % (designator, xKnots[i]))
                    else: # need a hard space if there is no negative sign
                        self.stringList.append('%s =  %-.16E' % (designator, xKnots[i]))

                self.stringList.append('<br>')

                for i in range(len(yKnots)):
                    designator = 'Y knot point ' + str(i)
                    if yKnots[i] < 0.0:
                        self.stringList.append('%s = %-.16E' % (designator, yKnots[i]))
                    else: # need a hard space if there is no negative sign
                        self.stringList.append('%s =  %-.16E' % (designator, yKnots[i]))

# enter in Text Reports at bottom
class CoefficientAndFitStatistics(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.equation.splineFlag:
            self.name = 'Fit Statistics'
        else:
            self.name = 'Coefficient and Fit Statistics'
        self.uniqueAnchorName = 'cfs'

    def CreateReportOutput(self):
        self.stringList.append('Most statstics from scipy.odr.odrpack and http://www.scipy.org/Cookbook/OLS')
        self.stringList.append('')
        self.stringList.append('LL, AIC and BIC from http://stackoverflow.com/questions/7458391/python-multiple-linear-regression-using-ols-code-with-specific-data')
        self.stringList.append('')
        self.stringList.append('If you entered coefficient bounds, parameter statistics may not be valid for parameter values at or near the bounds.')
        self.stringList.append('')

        self.stringList.append('Degrees of freedom (error):       ' + str(self.dataObject.equation.df_e))
        self.stringList.append('Degrees of freedom (regression):  ' + str(self.dataObject.equation.df_r))

        if self.dataObject.equation.sumOfSquaredErrors == None:
            self.stringList.append('Chi-squared:                      n/a')
        else:
            self.stringList.append('Chi-squared:                      ' + str(self.dataObject.equation.sumOfSquaredErrors))

        if self.dataObject.equation.r2 == None:
            self.stringList.append('R-squared:                        n/a')
        else:
            self.stringList.append('R-squared:                        ' + str(self.dataObject.equation.r2))

        if self.dataObject.equation.r2adj == None:
            self.stringList.append('R-squared adjusted:               n/a')
        else:
            self.stringList.append('R-squared adjusted:               ' + str(self.dataObject.equation.r2adj))

        if self.dataObject. equation.Fstat == None:
            self.stringList.append('Model F-statistic:                n/a')
        else:
            self.stringList.append('Model F-statistic:                ' + str(self.dataObject.equation.Fstat))

        if self.dataObject.equation.Fpv == None:
            self.stringList.append('Model F-statistic p-value:        n/a')
        else:
            self.stringList.append('Model F-statistic p-value:        ' + str(self.dataObject.equation.Fpv))

        if self.dataObject.equation.ll == None:
            self.stringList.append('Model log-likelihood:             n/a')
        else:
            self.stringList.append('Model log-likelihood:             ' + str(self.dataObject.equation.ll))

        if self.dataObject.equation.aic == None:
            self.stringList.append('AIC:                              n/a')
        else:
            self.stringList.append('AIC:                              ' + str(self.dataObject.equation.aic))

        if self.dataObject.equation.bic== None:
            self.stringList.append('BIC:                              n/a')
        else:
            self.stringList.append('BIC:                              ' + str(self.dataObject.equation.bic))

        if self.dataObject.equation.rmse == None:
            self.stringList.append('Root Mean Squared Error (RMSE):   n/a')
        else:
            self.stringList.append('Root Mean Squared Error (RMSE):   ' + str(self.dataObject.equation.rmse))

        if self.dataObject.equation.splineFlag:
            self.stringList.append('')
            return

        for i in range(len(self.dataObject.equation.solvedCoefficients)):
            if str(self.dataObject.equation.tstat_beta) == 'None':
                tstat = 'n/a'
            else:
                tstat = '%-.5E' %  (self.dataObject.equation.tstat_beta[i])

            if str(self.dataObject.equation.pstat_beta) == 'None':
                pstat = 'n/a'
            else:
                pstat = '%-.5E' %  (self.dataObject.equation.pstat_beta[i])

            self.stringList.append('\n%s = %-.16E' % (self.dataObject.equation.GetCoefficientDesignators()[i], self.dataObject.equation.solvedCoefficients[i]))
            try:
                self.stringList.append('&nbsp;       std err:                  %-.5E' % (self.dataObject.equation.sd_beta[i]))
            except:
                self.stringList.append('&nbsp;       std err:                  n/a<br>')
            self.stringList.append('&nbsp;       t-stat:                   ' + tstat)
            self.stringList.append('&nbsp;       p-stat:                   ' + pstat)
            self.stringList.append('&nbsp;       95% confidence intervals: ' + '[%-.5E, %-.5E]' % (self.dataObject.equation.ci[i][0], self.dataObject.equation.ci[i][1]))

        self.stringList.append('\nCoefficient Covariance Matrix:\n')
        for i in self.dataObject.equation.cov_beta:
            self.stringList.append(str(i))
        self.stringList.append('')

# enter in Text Reports at bottom
class ErrorListing(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        self.name = 'Error Listing'
        self.uniqueAnchorName = 'erl'

    def CreateReportOutput(self):
        datalen = len(self.dataObject.equation.dataCache.allDataCacheDictionary['DependentData'])

        # determine number of digits of precision for display
        dopIndep1 = 10
        dopIndep2 = 10
        dopDep = 10

        breakLoop = False
        for i in reversed(list(range(dopIndep1))):
            if breakLoop == True:
                break
            for j in range(datalen): # number of data points
                datapoint = self.dataObject.equation.dataCache.allDataCacheDictionary['IndependentData'][0][j]
                if float(('% .' + str(i+1) + 'E') % (datapoint)) != float(('% .' + str(i) + 'E') % (datapoint)):
                    dopIndep1 = i+1
                    breakLoop = True
                    break

        breakLoop = False
        for i in reversed(list(range(dopDep))):
            if breakLoop == True:
                break
            for j in range(datalen): # number of data points
                datapoint = self.dataObject.equation.dataCache.allDataCacheDictionary['DependentData'][j]
                if float(('% .' + str(i+1) + 'E') % (datapoint)) != float(('% .' + str(i) + 'E') % (datapoint)):
                    dopDep = i+1
                    breakLoop = True
                    break

        if self.dataObject.dimensionality == 3:
            breakLoop = False
            for i in reversed(list(range(dopIndep2))):
                if breakLoop == True:
                    break
                for j in range(datalen): # number of data points
                    datapoint = self.dataObject.equation.dataCache.allDataCacheDictionary['IndependentData'][1][j]
                    if float(('% .' + str(i+1) + 'E') % (datapoint)) != float(('% .' + str(i) + 'E') % (datapoint)):
                        dopIndep2 = i+1
                        breakLoop = True
                        break

        # now create report
        if self.dataObject.dimensionality == 2:
            self.stringList.append('Independent Data     Dependent Data      Predicted         Abs Error       Rel Error')
            self.stringList.append('')
            if str(self.dataObject.equation.modelRelativeError) == 'None':
                for i in range(datalen): # number of data points
                    tempString = '&nbsp; % .' + str(dopIndep1) + 'E          % .' + str(dopDep) + 'E     % .10E   % .6E   n/a'
                    self.stringList.append(tempString % (self.dataObject.equation.dataCache.allDataCacheDictionary['IndependentData'][0][i], self.dataObject.equation.dataCache.allDataCacheDictionary['DependentData'][i], self.dataObject.equation.modelPredictions[i], self.dataObject.equation.modelAbsoluteError[i]))
            else:
                for i in range(datalen): # number of data points
                    tempString = '&nbsp; % .' + str(dopIndep1) + 'E          % .' + str(dopDep) + 'E     % .10E   % .6E   % .6E'
                    self.stringList.append(tempString % (self.dataObject.equation.dataCache.allDataCacheDictionary['IndependentData'][0][i], self.dataObject.equation.dataCache.allDataCacheDictionary['DependentData'][i], self.dataObject.equation.modelPredictions[i], self.dataObject.equation.modelAbsoluteError[i], self.dataObject.equation.modelRelativeError[i]))
        else:
            self.stringList.append('&nbsp;Indep. Data 1     Indep. Data 2    Dependent Data       Predicted         Abs Error       Rel Error <td></tr>')
            self.stringList.append('')
            if str(self.dataObject.equation.modelRelativeError) == 'None':
                for i in range(datalen): # number of data points
                    tempString = '&nbsp; % .' + str(dopIndep1) + 'E        % .' + str(dopIndep2) + 'E       % .' + str(dopDep) + 'E      % .10E   % .6E   n/a'
                    self.stringList.append(tempString % (self.dataObject.equation.dataCache.allDataCacheDictionary['IndependentData'][0][i], self.dataObject.equation.dataCache.allDataCacheDictionary['IndependentData'][1][i], self.dataObject.equation.dataCache.allDataCacheDictionary['DependentData'][i], self.dataObject.equation.modelPredictions[i], self.dataObject.equation.modelAbsoluteError[i]))
            else:
                for i in range(datalen): # number of data points
                    tempString = '&nbsp; % .' + str(dopIndep1) + 'E        % .' + str(dopIndep2) + 'E       % .' + str(dopDep) + 'E      % .10E   % .6E   % .6E'
                    self.stringList.append(tempString % (self.dataObject.equation.dataCache.allDataCacheDictionary['IndependentData'][0][i], self.dataObject.equation.dataCache.allDataCacheDictionary['IndependentData'][1][i], self.dataObject.equation.dataCache.allDataCacheDictionary['DependentData'][i], self.dataObject.equation.modelPredictions[i], self.dataObject.equation.modelAbsoluteError[i], self.dataObject.equation.modelRelativeError[i]))

# enter in Text Reports at bottom
class StatisticsListing(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        self.name = 'Error Statistics'
        self.uniqueAnchorName = 'est'

    def CreateReportOutput(self):
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 0:
            self.stringList.append('&nbsp;                     Absolute Error   Relative Error\n')
            self.AddStatisticsToStringList(['abs_err', 'rel_err'])
        else:
            self.stringList.append('NOTE: Relative error statistics cannot be compiled, as at least one of')
            self.stringList.append('the dependent variable data points contains a value of exactly zero.\n')
            self.stringList.append('&nbsp;                    Absolute Error\n')
            self.AddStatisticsToStringList(['abs_err'])

# enter in Text Reports at bottom
class CharacterizerStatisticsListing(TextOnlyReport):

    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForCharacterizerOutput(self):
        self.name = 'Data Statistics'
        self.uniqueAnchorName = 'dst'

    def CreateCharacterizerOutput(self):
        if self.dataObject.dimensionality == 1:
            self.stringList.append('&nbsp;                           X\n')
            self.AddStatisticsToStringList(['1'])

        if self.dataObject.dimensionality == 2:
            self.stringList.append('&nbsp;                           X                Y\n')
            self.AddStatisticsToStringList(['1', '2'])

        if self.dataObject.dimensionality == 3:
            self.stringList.append('&nbsp;                           X                 Y               Z\n')
            self.AddStatisticsToStringList(['1', '2', '3'])

# enter in Text Reports at bottom
class StatisticalDistributions(TextOnlyReport):
    def __init__(self, dataObject):
        TextOnlyReport.__init__(self, dataObject)

    def PrepareForCharacterizerOutput(self):

        self.numberOfFittedDistributions = len(self.dataObject.fittedStatisticalDistributionsList)
        if self.numberOfFittedDistributions == 0:
            return

        self.name = 'Top ' + str(self.numberOfFittedDistributions) + ' Statistical Distributions'
        self.uniqueAnchorName = 'xsd'

    def CreateCharacterizerOutput(self):
        self.stringList.append('</pre><table style="font-family: monospace"><tr><td align="left">')

        # these are also in the graph reports
        rank = 1
        for i in self.dataObject.fittedStatisticalDistributionsList:
            self.stringList.append('<b>Rank ' + str(rank) + ': ' + i[1]['distributionLongName'] + ' distribution</b><BR>')
            rank += 1
            self.stringList.append('http://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.' + i[1]['distributionName'] + '.html<br>')

            self.stringList.append('<br>')

            self.stringList.append('Fit Statistics for ' + str(len(self.dataObject.IndependentDataArray[0])) + ' data points:<br>')
            self.stringList.append('&nbsp;   ' + 'Negative Two Log Likelihood = %-.16E<br>' % (2.0 * i[1]['nnlf']))
            if numpy.isfinite(i[1]['AIC']):
                self.stringList.append('&nbsp;   ' + 'AIC = %-.16E<br>' % (i[1]['AIC']))
            else:
                self.stringList.append('&nbsp;   ' + 'AIC = N/A<br>')
            if numpy.isfinite(i[1]['AICc_BA']):
                self.stringList.append('&nbsp;   ' + 'AICc (Burnham and Anderson) = %-.16E<br>' % (i[1]['AICc_BA']))
            else:
                self.stringList.append('&nbsp;   ' + 'AICc (Burnham and Anderson) = N/A<br>')

            self.stringList.append('<br><br>')

            self.stringList.append('Parameters:<BR>')
            for parmIndex in range(len(i[1]['parameterNames'])):
                self.stringList.append('&nbsp;   ' + i[1]['parameterNames'][parmIndex] + ' = %-.16E' % (i[1]['fittedParameters'][parmIndex]))

            self.stringList.append('<br>')

            self.stringList.append('Additional Information:')
            for infoString in i[1]['additionalInfo']:
                self.stringList.append(infoString.replace(' ', '&nbsp;'))

            self.stringList.append('<BR><BR><BR>')
        self.stringList.append('</td></tr></table><pre>')

class GraphReport(Report):

    def __init__(self, dataObject):
        Report.__init__(self, dataObject)
        self.DataGraph = 0
        self.HistogramFlag = 0
        self.StatisticsGraph = 1
        self.RequiresRelativeError = 0
        self.animationFlag = 0
        self.animationFrameSeparation = 2 # angular distance between animation frames
        self.rank = '' # function finders use rank to distinguish different graph reports

    def GetRankString(self):
        """Zero-padded rank suffix, base36, always three chars.

        Function finders set ``self.rank`` to an integer position in
        the ranked-equation list. Three base36 chars cover 0..46,655,
        sized to hold FunctionFinder's ~23K equation types across all
        families with headroom. All other report types leave rank as
        ``''`` and render as ``_000``. Fixed width keeps filenames
        sortable and avoids ambiguous parsing of trailing digits.
        """
        return '_' + b36(int(self.rank) if self.rank else 0, 3)

    def _buildFilePaths(self, ext):
        """Compose ``physicalFileLocation`` and ``websiteFileLocation``
        as ``{uniqueString}_{anchor}{rank}.{ext}`` under ``TEMP_FILES_DIR``
        and ``MEDIA_URL`` respectively. ``uniqueString`` already carries
        the ``zun_`` prefix (see _unique.new_unique_string).
        """
        name = '%s_%s%s.%s' % (
            self.dataObject.uniqueString,
            self.uniqueAnchorName,
            self.GetRankString(),
            ext,
        )
        self.physicalFileLocation = settings.TEMP_FILES_DIR + '/' + name
        self.websiteFileLocation = settings.MEDIA_URL + name

# enter in Graph Reports at bottom
class AbsoluteErrorHistogram(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.HistogramFlag = 1

    def PrepareForReportOutput(self):
        self.name = 'Histogram of Absolute Error'
        self.uniqueAnchorName = 'aeh'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.HistogramPlot(self.dataObject, self.physicalFileLocation, 'Absolute Error', self.dataObject.equation.modelAbsoluteError)

# enter in Graph Reports at bottom
class RelativeErrorHistogram(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.RequiresRelativeError = 1
        self.HistogramFlag = 1

    def PrepareForReportOutput(self):
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 1:
            self.name= ''
            return
        self.name = 'Histogram of Relative Error'
        self.uniqueAnchorName = 'reh'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.HistogramPlot(self.dataObject, self.physicalFileLocation, 'Relative Error', self.dataObject.equation.modelRelativeError)

# enter in Graph Reports at bottom
class PercentErrorHistogram(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.RequiresRelativeError = 1
        self.HistogramFlag = 1

    def PrepareForReportOutput(self):
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 1:
            self.name = '' # used as a 'do not create' flag
            return
        self.name = 'Histogram of Percent Error'
        self.uniqueAnchorName = 'peh'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.HistogramPlot(self.dataObject, self.physicalFileLocation, 'Percent Error', self.dataObject.equation.modelPercentError)

# enter in Graph Reports at bottom
class Data1Histogram(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.HistogramFlag = 1

    def PrepareForCharacterizerOutput(self):
        self.name = 'Histogram of ' + self.dataObject.IndependentDataName1
        self.uniqueAnchorName = 'xdh'
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        MatplotlibGraphs_2D.HistogramPlot(self.dataObject, self.physicalFileLocation, self.dataObject.IndependentDataName1, self.dataObject.IndependentDataArray[0])

# enter in Graph Reports at bottom
class Data2Histogram(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.HistogramFlag = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality != 3:
            return
        self.name = 'Histogram of ' + self.dataObject.IndependentDataName2
        self.uniqueAnchorName = 'ydh'
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        MatplotlibGraphs_2D.HistogramPlot(self.dataObject, self.physicalFileLocation, self.dataObject.IndependentDataName2, self.dataObject.IndependentDataArray[1])

# enter in Graph Reports at bottom
class DependentDataHistogram(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.HistogramFlag = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality == 1:
            return
        if self.dataObject.dimensionality == 2:
            self.uniqueAnchorName = 'ydh'
        else:
            self.uniqueAnchorName = 'zdh'
        self.name = 'Histogram of ' + self.dataObject.DependentDataName
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        MatplotlibGraphs_2D.HistogramPlot(self.dataObject, self.physicalFileLocation, self.dataObject.DependentDataName, self.dataObject.DependentDataArray)

# enter in Graph Reports at bottom
class AbsoluteErrorVsDependentData_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        self.name = 'Absolute Error vs. ' + self.dataObject.DependentDataName
        self.uniqueAnchorName = 'aed'
        self._buildFilePaths('png')
        if self.dataObject.dimensionality == 2:
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationY
            self.logLinXAxis = self.dataObject.logLinY
        else:
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationZ
            self.logLinXAxis = self.dataObject.logLinZ

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.DependentDataName, self.dataObject.DependentDataArray,  self.ScientificNotationXAxis,
                                      'Absolute Error',  self.dataObject.equation.modelAbsoluteError,  'AUTO',
                                      0, '', '',
                                      'LIN', self.logLinXAxis)

# enter in Graph Reports at bottom
class AbsoluteErrorVsIndependentData1_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        self.name = 'Absolute Error vs. ' + self.dataObject.IndependentDataName1
        self.uniqueAnchorName = 'ae1'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.IndependentDataName1, self.dataObject.IndependentDataArray[0], self.dataObject.ScientificNotationX,
                                      'Absolute Error', self.dataObject.equation.modelAbsoluteError, 'AUTO',
                                      0, '', '',
                                      'LIN', self.dataObject.logLinX)

# enter in Graph Reports at bottom
class AbsoluteErrorVsIndependentData2_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)

    def PrepareForReportOutput(self):
        if self.dataObject.dimensionality == 2:
            return
        self.name = 'Absolute Error vs. ' + self.dataObject.IndependentDataName2
        self.uniqueAnchorName = 'ae2'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.IndependentDataName2, self.dataObject.IndependentDataArray[1], self.dataObject.ScientificNotationY,
                                      'Absolute Error', self.dataObject.equation.modelAbsoluteError, 'AUTO',
                                      0, '', '',
                                      'LIN', self.dataObject.logLinY)

# enter in Graph Reports at bottom
class RelativeErrorVsDependentData_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.RequiresRelativeError = 1

    def PrepareForReportOutput(self):
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 1:
            return
        self.name = 'Relative Error vs. ' + self.dataObject.DependentDataName
        self.uniqueAnchorName = 'red'
        self._buildFilePaths('png')
        if self.dataObject.dimensionality == 2:
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationY
            self.logLinXAxis = self.dataObject.logLinY
        else:
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationZ
            self.logLinXAxis = self.dataObject.logLinZ

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.DependentDataName, self.dataObject.DependentDataArray, self.ScientificNotationXAxis,
                                      'Relative Error', self.dataObject.equation.modelRelativeError, 'AUTO',
                                      0, '', '',
                                      'LIN', self.logLinXAxis)

# enter in Graph Reports at bottom
class PercentErrorVsDependentData_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.RequiresRelativeError = 1

    def PrepareForReportOutput(self):
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 1:
            return
        self.name = 'Percent Error vs. ' + self.dataObject.DependentDataName
        self.uniqueAnchorName = 'ped'
        self._buildFilePaths('png')
        if self.dataObject.dimensionality == 2:
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationY
            self.logLinXAxis = self.dataObject.logLinY
        else:
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationZ
            self.logLinXAxis = self.dataObject.logLinZ

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.DependentDataName, self.dataObject.DependentDataArray, self.ScientificNotationXAxis,
                                      'Percent Error', self.dataObject.equation.modelPercentError, 'AUTO',
                                      0, '', '',
                                      'LIN', self.logLinXAxis)

# enter in Graph Reports at bottom
class RelativeErrorVsIndependentData1_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.RequiresRelativeError = 1

    def PrepareForReportOutput(self):
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 1:
            return
        self.name = 'Relative Error vs. ' + self.dataObject.IndependentDataName1
        self.uniqueAnchorName = 're1'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.IndependentDataName1, self.dataObject.IndependentDataArray[0], self.dataObject.ScientificNotationX,
                                      'Relative Error', self.dataObject.equation.modelRelativeError, 'AUTO',
                                      0, '', '',
                                      'LIN', self.dataObject.logLinX)

# enter in Graph Reports at bottom
class PercentErrorVsIndependentData1_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.RequiresRelativeError = 1

    def PrepareForReportOutput(self):
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 1:
            return
        self.name = 'Percent Error vs. ' + self.dataObject.IndependentDataName1
        self.uniqueAnchorName = 'pe1'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.IndependentDataName1, self.dataObject.IndependentDataArray[0], self.dataObject.ScientificNotationX,
                                      'Percent Error', self.dataObject.equation.modelPercentError, 'AUTO',
                                      0, '', '',
                                      'LIN', self.dataObject.logLinX)

# enter in Graph Reports at bottom
class RelativeErrorVsIndependentData2_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.RequiresRelativeError = 1

    def PrepareForReportOutput(self):
        if self.dataObject.dimensionality == 2:
            return
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 1:
            return
        self.name = 'Relative Error vs. ' + self.dataObject.IndependentDataName2
        self.uniqueAnchorName = 're2'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.IndependentDataName2, self.dataObject.IndependentDataArray[1], self.dataObject.ScientificNotationY,
                                      'Relative Error', self.dataObject.equation.modelRelativeError, 'AUTO',
                                      0, '', '',
                                      'LIN', self.dataObject.logLinY)

# enter in Graph Reports at bottom
class PercentErrorVsIndependentData2_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.RequiresRelativeError = 1

    def PrepareForReportOutput(self):
        if self.dataObject.dimensionality == 2:
            return
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 1:
            return
        self.name = 'Percent Error vs. ' + self.dataObject.IndependentDataName2
        self.uniqueAnchorName = 'pe2'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.IndependentDataName2, self.dataObject.IndependentDataArray[1], self.dataObject.ScientificNotationY,
                                      'Percent Error', self.dataObject.equation.modelPercentError, 'AUTO',
                                      0, '', '',
                                      'LIN', self.dataObject.logLinY)

# enter in Graph Reports at bottom
class DependentDataVsIndependentData1_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.DataGraph = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality == 1:
            return
        self.name = self.dataObject.DependentDataName + ' vs. ' + self.dataObject.IndependentDataName1
        self.uniqueAnchorName = 'dv1'
        self._buildFilePaths('png')
        if self.dataObject.dimensionality == 2:
            self.YorZ = 'Y'
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationY
            self.logLinYAxis = self.dataObject.logLinY
        else:
            self.YorZ = 'Z'
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationZ
            self.logLinYAxis = self.dataObject.logLinZ

    def CreateCharacterizerOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.IndependentDataName1, self.dataObject.IndependentDataArray[0], self.dataObject.ScientificNotationX,
                                      self.dataObject.DependentDataName, self.dataObject.DependentDataArray, self.ScientificNotationXAxis,
                                      1, 'X', self.YorZ,
                                      self.logLinYAxis, self.dataObject.logLinX)

# enter in Graph Reports at bottom
class DependentDataVsIndependentData1_ModelPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.DataGraph = 1

    def PrepareForReportOutput(self):

        self.name = self.dataObject.DependentDataName + ' vs. ' + self.dataObject.IndependentDataName1
        if self.dataObject.dimensionality == 2:
            self.name += ' with model'
        else:
            self.name = ''
        self.uniqueAnchorName = 'mp1'
        self._buildFilePaths('png')
        if self.dataObject.dimensionality == 2:
            self.YorZ = 'Y'
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationY
            self.logLinYAxis = self.dataObject.logLinY
        else:
            self.YorZ = 'Z'
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationZ
            self.logLinYAxis = self.dataObject.logLinZ

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ModelAndScatterPlot(self.dataObject, self.physicalFileLocation,
                                          self.dataObject.IndependentDataName1,
                                          self.dataObject.DependentDataName,
                                          0,
                                          self.logLinYAxis, self.dataObject.logLinX,
                                          False)

# enter in Graph Reports at bottom
class DependentDataVsIndependentData1_ConfidenceIntervals(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.DataGraph = 1

    def PrepareForReportOutput(self):
        self.name = self.dataObject.DependentDataName + ' vs. ' + self.dataObject.IndependentDataName1
        if self.dataObject.dimensionality == 2:
            self.name += ' with 95% confidence intervals'
        else:
            self.name = ''
        self.uniqueAnchorName = 'ci1'
        self._buildFilePaths('png')
        if self.dataObject.dimensionality == 2:
            self.YorZ = 'Y'
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationY
            self.logLinYAxis = self.dataObject.logLinY
        else:
            self.YorZ = 'Z'
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationZ
            self.logLinYAxis = self.dataObject.logLinZ

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ModelAndScatterPlot(self.dataObject, self.physicalFileLocation,
                                          self.dataObject.IndependentDataName1,
                                          self.dataObject.DependentDataName,
                                          0,
                                          self.logLinYAxis, self.dataObject.logLinX,
                                          True)

# enter in Graph Reports at bottom
class DependentDataVsIndependentData2_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.DataGraph = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality != 3:
            return
        self.name = self.dataObject.DependentDataName + ' vs. ' + self.dataObject.IndependentDataName2
        self.uniqueAnchorName = 'dv2'
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.IndependentDataName2, self.dataObject.IndependentDataArray[1], self.dataObject.ScientificNotationY,
                                      self.dataObject.DependentDataName, self.dataObject.DependentDataArray, self.dataObject.ScientificNotationZ,
                                      1, 'Y', 'Z',
                                      self.dataObject.logLinZ, self.dataObject.logLinY)

# enter in Graph Reports at bottom
class IndependentData1VsDependentData_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.DataGraph = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality == 1:
            return
        self.name = self.dataObject.IndependentDataName1 + ' vs. ' + self.dataObject.DependentDataName
        self.uniqueAnchorName = 'i1d'
        self._buildFilePaths('png')
        if self.dataObject.dimensionality == 2:
            self.YorZ = 'Y'
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationY
            self.logLinXAxis = self.dataObject.logLinY
        else:
            self.YorZ = 'Z'
            self.ScientificNotationXAxis = self.dataObject.ScientificNotationZ
            self.logLinXAxis = self.dataObject.logLinZ

    def CreateCharacterizerOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.DependentDataName, self.dataObject.DependentDataArray, self.ScientificNotationXAxis,
                                      self.dataObject.IndependentDataName1, self.dataObject.IndependentDataArray[0], self.dataObject.ScientificNotationX,
                                      1, self.YorZ, 'X',
                                      self.dataObject.logLinX, self.logLinXAxis)

# enter in Graph Reports at bottom
class IndependentData1VsIndependentData2_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.DataGraph = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality != 3:
            return
        self.name = self.dataObject.IndependentDataName1 + ' vs. ' + self.dataObject.IndependentDataName2
        self.uniqueAnchorName = 'i12'
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.IndependentDataName2, self.dataObject.IndependentDataArray[1], self.dataObject.ScientificNotationY,
                                      self.dataObject.IndependentDataName1, self.dataObject.IndependentDataArray[0], self.dataObject.ScientificNotationX,
                                      1, 'Y', 'X',
                                      self.dataObject.logLinX, self.dataObject.logLinY)

# enter in Graph Reports at bottom
class IndependentData2VsDependentData_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.DataGraph = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality != 3:
            return
        self.name = self.dataObject.IndependentDataName2 + ' vs. ' + self.dataObject.DependentDataName
        self.uniqueAnchorName = 'i2d'
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.DependentDataName, self.dataObject.DependentDataArray, self.dataObject.ScientificNotationZ,
                                      self.dataObject.IndependentDataName2, self.dataObject.IndependentDataArray[1], self.dataObject.ScientificNotationY,
                                      1, 'Z', 'Y',
                                      self.dataObject.logLinY, self.dataObject.logLinZ)

# enter in Graph Reports at bottom
class IndependentData2VsIndependentData1_ScatterPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.DataGraph = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality != 3:
            return
        self.name = self.dataObject.IndependentDataName2 + ' vs. ' + self.dataObject.IndependentDataName1
        self.uniqueAnchorName = 'i21'
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        MatplotlibGraphs_2D.ScatterPlot(self.dataObject, self.physicalFileLocation,
                                      self.dataObject.IndependentDataName1, self.dataObject.IndependentDataArray[0], self.dataObject.ScientificNotationX,
                                      self.dataObject.IndependentDataName2, self.dataObject.IndependentDataArray[1], self.dataObject.ScientificNotationY,
                                      1, 'X', 'Y',
                                      self.dataObject.logLinY, self.dataObject.logLinX)

# enter in Graph Reports at bottom
class AbsErrScatterPlot3D(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality != 3:
            return
        self.name = 'Absolute Error Scatter Plot'
        self.uniqueAnchorName = 'as3'
        self.dataObject.ScientificNotationZ = 'AUTO'
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        self.dataObject.DependentDataName = 'Absolute Error'
        self.dataObject.DependentDataArray = self.dataObject.equation.modelAbsoluteError
        self.dataObject.CalculateDataStatistics()
        self.Extrapolation_z = 0.05
        self.dataObject.CalculateGraphBoundaries()
        from . import MatplotlibGraphs_3D
        MatplotlibGraphs_3D.ScatterPlot3D(self.dataObject, self.physicalFileLocation)

# enter in Graph Reports at bottom
class RelErrScatterPlot3D(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.RequiresRelativeError = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality != 3:
            return
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 1:
            self.name= ''
            return
        self.name = 'Relative Error Scatter Plot'
        self.uniqueAnchorName = 'rs3'
        self.dataObject.ScientificNotationZ = 'AUTO'
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        self.dataObject.DependentDataName = 'Relative Error'
        self.dataObject.DependentDataArray = self.dataObject.equation.modelRelativeError
        self.dataObject.CalculateDataStatistics()
        self.Extrapolation_z = 0.05
        self.dataObject.CalculateGraphBoundaries()
        from . import MatplotlibGraphs_3D
        MatplotlibGraphs_3D.ScatterPlot3D(self.dataObject, self.physicalFileLocation)

# enter in Graph Reports at bottom
class PerErrScatterPlot3D(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.RequiresRelativeError = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality != 3:
            return
        if self.dataObject.equation.dataCache.DependentDataContainsZeroFlag == 1:
            self.name= ''
            return
        self.name = 'Percent Error Scatter Plot'
        self.uniqueAnchorName = 'ps3'
        self.dataObject.ScientificNotationZ = 'AUTO'
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        self.dataObject.DependentDataName = 'Percent Error'
        self.dataObject.DependentDataArray = self.dataObject.equation.modelPercentError
        self.dataObject.CalculateDataStatistics()
        self.Extrapolation_z = 0.05
        self.dataObject.CalculateGraphBoundaries()
        from . import MatplotlibGraphs_3D
        MatplotlibGraphs_3D.ScatterPlot3D(self.dataObject, self.physicalFileLocation)

# enter in Graph Reports at bottom
class ScatterPlot3D(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.DataGraph = 1

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality != 3:
            return
        self.name = 'Scatter Plot'
        self.uniqueAnchorName = 'sp3'
        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        from . import MatplotlibGraphs_3D
        MatplotlibGraphs_3D.ScatterPlot3D(self.dataObject, self.physicalFileLocation)

# enter in Graph Reports at bottom
class SurfacePlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0

    def PrepareForReportOutput(self):
        if self.dataObject.dimensionality == 2:
            return
        self.name = 'Surface Plot'
        self.uniqueAnchorName = 'sur'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        from . import MatplotlibGraphs_3D
        MatplotlibGraphs_3D.SurfacePlot(self.dataObject, self.physicalFileLocation)

# enter in Graph Reports at bottom
class ContourPlot(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0

    def PrepareForReportOutput(self):
        if self.dataObject.dimensionality == 2:
            return
        self.name = 'Contour Plot'
        self.uniqueAnchorName = 'con'
        self._buildFilePaths('png')

    def CreateReportOutput(self):
        MatplotlibGraphs_2D.ContourPlot(self.dataObject, self.physicalFileLocation)

# enter in Graph Reports at bottom
class StatisticalDistributionHistogram(GraphReport):

    def __init__(self, dataObject, distributionIndex):
        GraphReport.__init__(self, dataObject)
        self.HistogramFlag = 1
        self.distributionIndex = distributionIndex

    def PrepareForCharacterizerOutput(self):
        self.name= ''

        self.numberOfFittedDistributions = len(self.dataObject.fittedStatisticalDistributionsList)
        if self.numberOfFittedDistributions <= self.distributionIndex:
            return

        i = self.dataObject.fittedStatisticalDistributionsList[self.distributionIndex]

        # these are also in the text reports
        self.stringList.append('</pre><table style="font-family: monospace"><tr><td align="left">')
        self.stringList.append(i[1]['distributionLongName'] + ' distribution<BR>')
        self.stringList.append('http://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.' + i[1]['distributionName'] + '.html<BR>')

        self.stringList.append('<br>')

        self.stringList.append('Fit Statistics for ' + str(len(self.dataObject.IndependentDataArray[0])) + ' data points:<br>')
        self.stringList.append('&nbsp;   ' + 'Negative Two Log Likelihood = %-.16E<br>' % (2.0 * i[1]['nnlf']))
        if numpy.isfinite(i[1]['AIC']):
            self.stringList.append('&nbsp;   ' + 'AIC = %-.16E<br>' % (i[1]['AIC']))
        else:
            self.stringList.append('&nbsp;   ' + 'AIC = N/A<br>')
        if numpy.isfinite(i[1]['AICc_BA']):
            self.stringList.append('&nbsp;   ' + 'AICc (Burnham and Anderson) = %-.16E<br>' % (i[1]['AICc_BA']))
        else:
            self.stringList.append('&nbsp;   ' + 'AICc (Burnham and Anderson) = N/A<br>')

        self.stringList.append('<br><br>')

        self.stringList.append('Parameters:<BR>')
        for parmIndex in range(len(i[1]['parameterNames'])):
            self.stringList.append('&nbsp;   ' + i[1]['parameterNames'][parmIndex] + ' = %-.16E' % (i[1]['fittedParameters'][parmIndex]))

        self.stringList.append('<br>')

        self.stringList.append('Additional Information:')
        for infoString in i[1]['additionalInfo']:
            self.stringList.append(infoString.replace(' ', '&nbsp;'))

        self.stringList.append('</td></tr></table><pre>')

        self.name = 'Rank ' + str(self.distributionIndex + 1) + ': ' + i[1]['distributionLongName']
        # Parametrized: 'xs' + base36 of distributionIndex (0..35).
        # 'xsd' (XStatDist summary report) is the related fixed anchor.
        idx = self.distributionIndex
        idx_char = '0123456789abcdefghijklmnopqrstuvwxyz'[idx] if 0 <= idx < 36 else 'z'
        self.uniqueAnchorName = 'xs' + idx_char

        self._buildFilePaths('png')

    def CreateCharacterizerOutput(self):
        self.dataObject.distributionIndex = self.distributionIndex

        distro = self.dataObject.fittedStatisticalDistributionsList[self.distributionIndex][1]

        MatplotlibGraphs_2D.HistogramPlot(self.dataObject,
                                       self.physicalFileLocation,
                                       distro['distributionLongName'] + ' distribution',
                                       self.dataObject.IndependentDataArray[0],
                                       1)

# enter in Graph Reports at bottom
class ScatterAnimation(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.animationFlag = 1
        self.DataGraph = 1

        # used in creating individual animation frames on clusters
        self.functionString = 'MatplotlibGraphs_3D.ScatterPlot3D'

    def PrepareForCharacterizerOutput(self):
        if self.dataObject.dimensionality == 2:
            return
        if self.dataObject.animationHeight == 0:
            return

        self.name = 'GIF Scatter Animation'
        self.uniqueAnchorName = 'san'
        self._buildFilePaths('gif')

    def CreateCharacterizerOutput(self):
        from . import MatplotlibGraphs_3D

        self.dataObject.graphHeight = self.dataObject.animationHeight
        self.dataObject.graphWidth = self.dataObject.animationWidth
        self.dataObject.CalculateGraphBoundaries()

        try:
            [fig, ax, plt] = eval(self.functionString + '(self.dataObject, None)')

            elev = self.dataObject.altimuth3D
            def _update(azim):
                ax.view_init(elev=elev, azim=azim)

            anim = FuncAnimation(
                fig,
                _update,
                frames=range(0, 360, self.animationFrameSeparation),
                blit=False,
            )
            anim.save(self.physicalFileLocation, writer=PillowWriter(fps=10))
            plt.close('all')
        except:
            import logging
            logging.basicConfig(filename = os.path.join(settings.TEMP_FILES_DIR, str(os.getpid()) + '.log'), level=logging.DEBUG)
            logging.exception('Exception creating GIF animation')

# enter in Graph Reports at bottom
class SurfaceAnimation(GraphReport):

    def __init__(self, dataObject):
        GraphReport.__init__(self, dataObject)
        self.StatisticsGraph = 0
        self.animationFlag = 1

        # used in creating individual animation frames on clusters
        self.functionString = 'MatplotlibGraphs_3D.SurfacePlot'

    def PrepareForReportOutput(self):
        if self.dataObject.dimensionality == 2:
            return
        if self.dataObject.animationHeight == 0:
            return

        self.name = 'GIF Surface Animation'
        self.uniqueAnchorName = 'sua'
        self._buildFilePaths('gif')

    def CreateReportOutput(self):
        try:
            from . import MatplotlibGraphs_3D

            self.dataObject.graphHeight = self.dataObject.animationHeight
            self.dataObject.graphWidth = self.dataObject.animationWidth
            self.dataObject.CalculateGraphBoundaries()

            [fig, ax, plt] = eval(self.functionString + '(self.dataObject, None)')

            elev = self.dataObject.altimuth3D
            def _update(azim):
                ax.view_init(elev=elev, azim=azim)

            anim = FuncAnimation(
                fig,
                _update,
                frames=range(0, 360, self.animationFrameSeparation),
                blit=False,
            )
            anim.save(self.physicalFileLocation, writer=PillowWriter(fps=10))
            plt.close('all')
        except:
            import logging
            logging.basicConfig(filename = os.path.join(settings.TEMP_FILES_DIR, str(os.getpid()) + '.log'), level=logging.DEBUG)
            logging.exception('Exception creating GIF animation')

def StatisticalDistributionReportsDict(dataObject):
    return {'Text Reports' : [CharacterizerStatisticsListing(dataObject),
                              StatisticalDistributions(dataObject)],
            'Graph Reports' : [Data1Histogram(dataObject),
                               StatisticalDistributionHistogram(dataObject,  0),
                               StatisticalDistributionHistogram(dataObject,  1),
                               StatisticalDistributionHistogram(dataObject,  2),
                               StatisticalDistributionHistogram(dataObject,  3),
                               StatisticalDistributionHistogram(dataObject,  4),
                               StatisticalDistributionHistogram(dataObject,  5),
                               StatisticalDistributionHistogram(dataObject,  6),
                               StatisticalDistributionHistogram(dataObject,  7),
                               StatisticalDistributionHistogram(dataObject,  8),
                               StatisticalDistributionHistogram(dataObject,  9),
                               StatisticalDistributionHistogram(dataObject, 10),
                               StatisticalDistributionHistogram(dataObject, 11),
                               StatisticalDistributionHistogram(dataObject, 12),
                               StatisticalDistributionHistogram(dataObject, 13),
                               StatisticalDistributionHistogram(dataObject, 14),
                               StatisticalDistributionHistogram(dataObject, 15),
                               StatisticalDistributionHistogram(dataObject, 16),
                               StatisticalDistributionHistogram(dataObject, 17),
                               StatisticalDistributionHistogram(dataObject, 18),
                               StatisticalDistributionHistogram(dataObject, 19),
                               StatisticalDistributionHistogram(dataObject, 20),
                               StatisticalDistributionHistogram(dataObject, 21),
                               StatisticalDistributionHistogram(dataObject, 22),
                               StatisticalDistributionHistogram(dataObject, 23),
                               StatisticalDistributionHistogram(dataObject, 24),
                               StatisticalDistributionHistogram(dataObject, 25),
                               StatisticalDistributionHistogram(dataObject, 26),
                               StatisticalDistributionHistogram(dataObject, 27),
                               StatisticalDistributionHistogram(dataObject, 28),
                               StatisticalDistributionHistogram(dataObject, 29),
                               StatisticalDistributionHistogram(dataObject, 30),
                               StatisticalDistributionHistogram(dataObject, 31),
                               StatisticalDistributionHistogram(dataObject, 32),
                               StatisticalDistributionHistogram(dataObject, 33),
                               StatisticalDistributionHistogram(dataObject, 34),
                               StatisticalDistributionHistogram(dataObject, 35),
                               StatisticalDistributionHistogram(dataObject, 36),
                               StatisticalDistributionHistogram(dataObject, 37),
                               StatisticalDistributionHistogram(dataObject, 38),
                               StatisticalDistributionHistogram(dataObject, 39),
                               StatisticalDistributionHistogram(dataObject, 40),
                               StatisticalDistributionHistogram(dataObject, 41),
                               StatisticalDistributionHistogram(dataObject, 42),
                               StatisticalDistributionHistogram(dataObject, 43),
                               StatisticalDistributionHistogram(dataObject, 44),
                               StatisticalDistributionHistogram(dataObject, 45),
                               StatisticalDistributionHistogram(dataObject, 46),
                               StatisticalDistributionHistogram(dataObject, 47),
                               StatisticalDistributionHistogram(dataObject, 48),
                               StatisticalDistributionHistogram(dataObject, 49),
                               StatisticalDistributionHistogram(dataObject, 50),
                               StatisticalDistributionHistogram(dataObject, 51),
                               StatisticalDistributionHistogram(dataObject, 52),
                               StatisticalDistributionHistogram(dataObject, 53),
                               StatisticalDistributionHistogram(dataObject, 54),
                               StatisticalDistributionHistogram(dataObject, 55),
                               StatisticalDistributionHistogram(dataObject, 56),
                               StatisticalDistributionHistogram(dataObject, 57),
                               StatisticalDistributionHistogram(dataObject, 58),
                               StatisticalDistributionHistogram(dataObject, 59),
                               StatisticalDistributionHistogram(dataObject, 60),
                               StatisticalDistributionHistogram(dataObject, 61),
                               StatisticalDistributionHistogram(dataObject, 62),
                               StatisticalDistributionHistogram(dataObject, 63),
                               StatisticalDistributionHistogram(dataObject, 64),
                               StatisticalDistributionHistogram(dataObject, 65),
                               StatisticalDistributionHistogram(dataObject, 66),
                               StatisticalDistributionHistogram(dataObject, 67),
                               StatisticalDistributionHistogram(dataObject, 68),
                               StatisticalDistributionHistogram(dataObject, 69),
                               StatisticalDistributionHistogram(dataObject, 70),
                               StatisticalDistributionHistogram(dataObject, 71),
                               StatisticalDistributionHistogram(dataObject, 72),
                               StatisticalDistributionHistogram(dataObject, 73),
                               StatisticalDistributionHistogram(dataObject, 74),
                               StatisticalDistributionHistogram(dataObject, 75),
                               StatisticalDistributionHistogram(dataObject, 76),
                               StatisticalDistributionHistogram(dataObject, 77),
                               StatisticalDistributionHistogram(dataObject, 78),
                               StatisticalDistributionHistogram(dataObject, 79),
                               StatisticalDistributionHistogram(dataObject, 80),
                               StatisticalDistributionHistogram(dataObject, 81),
                               StatisticalDistributionHistogram(dataObject, 82),
                               StatisticalDistributionHistogram(dataObject, 83),
                               StatisticalDistributionHistogram(dataObject, 84),
                               StatisticalDistributionHistogram(dataObject, 85),
                               StatisticalDistributionHistogram(dataObject, 86),
                               StatisticalDistributionHistogram(dataObject, 87),
                               StatisticalDistributionHistogram(dataObject, 88),
                               StatisticalDistributionHistogram(dataObject, 89),
                               StatisticalDistributionHistogram(dataObject, 90),
                               StatisticalDistributionHistogram(dataObject, 91),
                               StatisticalDistributionHistogram(dataObject, 92),
                               StatisticalDistributionHistogram(dataObject, 93),
                               StatisticalDistributionHistogram(dataObject, 94),
                               StatisticalDistributionHistogram(dataObject, 95),
                               StatisticalDistributionHistogram(dataObject, 96),
                               StatisticalDistributionHistogram(dataObject, 97),
                               StatisticalDistributionHistogram(dataObject, 98),
                               StatisticalDistributionHistogram(dataObject, 99)]
            }

def CharacterizerReportsDict(dataObject):
    return {'Text Reports' : [CharacterizerStatisticsListing(dataObject)],
            'Graph Reports' : [Data1Histogram(dataObject),
                               Data2Histogram(dataObject),
                               DependentDataHistogram(dataObject),
                               DependentDataVsIndependentData1_ScatterPlot(dataObject),
                               DependentDataVsIndependentData2_ScatterPlot(dataObject),
                               IndependentData1VsDependentData_ScatterPlot(dataObject),
                               IndependentData1VsIndependentData2_ScatterPlot(dataObject),
                               IndependentData2VsDependentData_ScatterPlot(dataObject),
                               IndependentData2VsIndependentData1_ScatterPlot(dataObject),
                               ScatterPlot3D(dataObject),
                               ScatterAnimation(dataObject),
                               ]
            }

def FittingReportsDict(dataObject):
    return {'Text Reports' : [UserDefinedFunctionText(dataObject),
                              CoefficientListing(dataObject),
                              CoefficientAndFitStatistics(dataObject),
                              ErrorListing(dataObject),
                              StatisticsListing(dataObject),
                              CharacterizerStatisticsListing(dataObject),
                              CodeReportCPP(dataObject),
                              CodeReportFORTRAN90(dataObject),
                              CodeReportJAVA(dataObject),
                              CodeReportJULIA(dataObject),
                              CodeReportJAVASCRIPT(dataObject),
                              CodeReportPYTHON(dataObject),
                              CodeReportCSHARP(dataObject),
                              CodeReportSCILAB(dataObject),
                              CodeReportMATLAB(dataObject),
                              CodeReportVBA(dataObject)],
            'Graph Reports' : [Data1Histogram(dataObject),
                               Data2Histogram(dataObject),
                               DependentDataHistogram(dataObject),
                               AbsoluteErrorHistogram(dataObject),
                               RelativeErrorHistogram(dataObject),
                               PercentErrorHistogram(dataObject),
                               AbsoluteErrorVsIndependentData1_ScatterPlot(dataObject),
                               AbsoluteErrorVsIndependentData2_ScatterPlot(dataObject),
                               AbsoluteErrorVsDependentData_ScatterPlot(dataObject),
                               AbsErrScatterPlot3D(dataObject),
                               RelativeErrorVsIndependentData1_ScatterPlot(dataObject),
                               RelativeErrorVsIndependentData2_ScatterPlot(dataObject),
                               RelativeErrorVsDependentData_ScatterPlot(dataObject),
                               RelErrScatterPlot3D(dataObject),
                               PercentErrorVsIndependentData1_ScatterPlot(dataObject),
                               PercentErrorVsIndependentData2_ScatterPlot(dataObject),
                               PercentErrorVsDependentData_ScatterPlot(dataObject),
                               PerErrScatterPlot3D(dataObject),
                               DependentDataVsIndependentData1_ScatterPlot(dataObject),
                               DependentDataVsIndependentData2_ScatterPlot(dataObject),
                               IndependentData1VsDependentData_ScatterPlot(dataObject),
                               IndependentData1VsIndependentData2_ScatterPlot(dataObject),
                               IndependentData2VsDependentData_ScatterPlot(dataObject),
                               IndependentData2VsIndependentData1_ScatterPlot(dataObject),
                               DependentDataVsIndependentData1_ModelPlot(dataObject),
                               DependentDataVsIndependentData1_ConfidenceIntervals(dataObject),
                               ScatterPlot3D(dataObject),
                               SurfacePlot(dataObject),
                               ContourPlot(dataObject),
                               ScatterAnimation(dataObject),
                               SurfaceAnimation(dataObject),
                               ]
            }
