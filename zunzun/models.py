import secrets

from django.db import models

from zunzun.session_helpers import NumpyJSONEncoder


class LRPStatus(models.Model):
    """Per-dispatch status row for a long-running fit.

    One row per fit DISPATCH (not per user): the autopk ``id`` is the
    dispatch identity, replacing the old ``dispatched_at`` ownership float
    from the JSON-session-blob era. The current dispatch's pk is stored in
    ``request.session['lrp_status_pk']`` and StatusView follows that pointer.
    Older rows are simply unreferenced once the session pointer moves to a new
    dispatch's row, and are reclaimed by the age-sweep in the housekeeping
    child. Because each fit writes only its own row, there is no shared
    cell to race on and no ownership check is needed on writes.
    """

    class State(models.TextChoices):
        INITIALIZING = "initializing", "Initializing"
        RUNNING = "running", "Running"
        TERMINAL = "terminal", "Terminal"

    # TextField (unbounded), not CharField(255): the FunctionFinder progress
    # path writes an HTML <table> with one row per included equation family
    # (WorkItems_CheckOneSecondSessionUpdates), which exceeds 255 chars on a
    # normal multi-family run. update_status uses .update() (no Django-level
    # length validation) and SQLite ignores VARCHAR length, so a cap is a
    # silent footgun that would only bite a length-enforcing backend mid-fit.
    # Matches redirect_to_results.
    current_status = models.TextField(default="Initializing")
    start_time = models.FloatField(default=0.0)
    last_status_check = models.FloatField(default=0.0)
    redirect_to_results = models.TextField(default="")
    parallel_count = models.IntegerField(default=0)
    process_id = models.IntegerField(default=0)
    state = models.CharField(max_length=12, choices=State.choices, default=State.INITIALIZING)
    owner_session_key = models.CharField(max_length=40, db_index=True, default="")
    owner_ip = models.CharField(max_length=45, db_index=True, default="")  # 45 = max IPv6 text len
    # default=secrets.token_urlsafe → every row auto-mints a unique 43-char
    # token (token_urlsafe(32) = 43 chars), so no create() site can forget it.
    result_token = models.CharField(
        max_length=43, unique=True, db_index=True, default=secrets.token_urlsafe
    )

    def is_owned_by(self, session_key):
        """Owned iff the requesting session has a non-empty key matching this
        row's owner. Empty/None keys are never owners (an empty owner_session_key
        default must not be reachable by a keyless client)."""
        return bool(session_key) and self.owner_session_key == session_key

    @classmethod
    def mark_running(cls, pk, pid):
        """INITIALIZING -> RUNNING. The child claims the row with its pid.

        Filtered on state=INITIALIZING so TERMINAL stays absorbing: if the
        dead-pid backstop (views._finalize_row_if_child_dead) already finalized
        this row -- because a slow-starting child had not written its pid within
        the 60s pending window -- a late claim is a no-op rather than
        resurrecting the terminal row back to RUNNING. Restores the
        pre-state-field behavior, where the claim wrote only process_id and never
        cleared the durable terminal flag.
        """
        cls.objects.filter(pk=pk, state=cls.State.INITIALIZING).update(
            state=cls.State.RUNNING, process_id=pid
        )

    @classmethod
    def mark_terminal(cls, pk, *, redirect=None, current_status=None, parallel_count=None):
        """-> TERMINAL. Always sets state=TERMINAL and process_id=0 together so
        the terminal tuple can never be set partially. Optional fields are
        written ONLY when passed, so a bare mark_terminal(pk) never clobbers a
        redirect a prior successful stage already published. Uses
        .filter(pk).update() (not instance.save()): a no-op if the housekeeping
        age-sweep deleted the row."""
        fields = {"state": cls.State.TERMINAL, "process_id": 0}
        if redirect is not None:
            fields["redirect_to_results"] = redirect
        if current_status is not None:
            fields["current_status"] = current_status
        if parallel_count is not None:
            fields["parallel_count"] = parallel_count
        cls.objects.filter(pk=pk).update(**fields)


class LRPDispatchData(models.Model):
    """Per-dispatch data payload, replacing the per-session `data` and
    `functionfinder` SessionStores. OneToOne to LRPStatus with cascade so the
    data's lifetime is bolted to the dispatch row — deleting the status row
    housekeeping age-sweep drops the data atomically, no orphan sweep.
    Written by spawn children under SQLite contention, so callers go through
    zunzun.dispatch_data's retry helpers, never a bare .save().
    """

    status = models.OneToOneField(LRPStatus, on_delete=models.CASCADE, related_name="dispatch_data")
    data = models.JSONField(default=dict, encoder=NumpyJSONEncoder)
    functionfinder = models.JSONField(default=dict, encoder=NumpyJSONEncoder)
