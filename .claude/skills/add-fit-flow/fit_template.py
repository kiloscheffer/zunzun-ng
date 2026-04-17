# Scaffold for a new fit flow. Copy to zunzun/LongRunningProcess/FitMyNewFit.py,
# rename the class, and register it in zunzun/LongRunningProcess/__init__.py.
#
# See .claude/skills/add-fit-flow/SKILL.md for the full checklist.

from . import FittingBaseClass


class FitMyNewFit(FittingBaseClass.FittingBaseClass):

    def __init__(self):
        FittingBaseClass.FittingBaseClass.__init__(self)

        # template used when LongRunningProcessView GETs the interface page
        self.interfaceString = 'zunzun/equation_fit_interface.html'

        # if False, POST goes straight through without form validation
        self.userInterfaceRequired = True

        # os.nice() value for the forked child (higher = lower priority)
        self.reniceLevel = 10

    def GenerateListOfWorkItems(self):
        # Populate self.workItemsList with the units of work to dispatch
        # across the multiprocessing pool. Each item must be picklable.
        raise NotImplementedError

    def PerformWorkInParallel(self):
        # Drive the pool; at minimum, update status via
        # self.SaveDictionaryOfItemsToSessionStore('status', {...}) so
        # StatusView shows progress during the long-running work.
        raise NotImplementedError
