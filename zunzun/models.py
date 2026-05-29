from django.db import models


class LRPStatus(models.Model):
    """Per-dispatch status row for a long-running fit.

    One row per fit DISPATCH (not per user): the autopk ``id`` is the
    dispatch identity, replacing the old ``dispatched_at`` ownership float
    from the JSON-session-blob era. The current dispatch's pk is stored in
    ``request.session['lrp_status_pk']`` and StatusView follows that pointer.
    Older/superseded rows are simply unreferenced and reclaimed by cleanup
    (delete-prior-row on new dispatch + an age sweep in the housekeeping
    child). Because each fit writes only its own row, there is no shared
    cell to race on and no ownership check is needed on writes.
    """

    current_status = models.CharField(max_length=255, default="Initializing")
    start_time = models.FloatField(default=0.0)
    last_status_check = models.FloatField(default=0.0)
    redirect_to_results = models.TextField(default="")
    parallel_count = models.IntegerField(default=0)
    process_id = models.IntegerField(default=0)
