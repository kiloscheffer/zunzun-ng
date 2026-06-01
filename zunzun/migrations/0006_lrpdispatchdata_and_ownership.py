import secrets

import django.db.models.deletion
from django.db import migrations, models


def backfill_tokens(apps, schema_editor):
    LRPStatus = apps.get_model("zunzun", "LRPStatus")
    for row in LRPStatus.objects.filter(result_token__isnull=True).only("id"):
        LRPStatus.objects.filter(pk=row.pk).update(result_token=secrets.token_urlsafe(32))


class Migration(migrations.Migration):
    dependencies = [("zunzun", "0005_remove_lrpstatus_completed")]

    operations = [
        migrations.AddField(
            "lrpstatus",
            "owner_session_key",
            models.CharField(db_index=True, default="", max_length=40),
        ),
        migrations.AddField(
            "lrpstatus",
            "owner_ip",
            models.CharField(db_index=True, default="", max_length=45),
        ),
        # Three-step unique column: nullable -> backfill -> non-null unique.
        migrations.AddField(
            "lrpstatus",
            "result_token",
            models.CharField(max_length=43, null=True),
        ),
        migrations.RunPython(backfill_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            "lrpstatus",
            "result_token",
            models.CharField(
                db_index=True, default=secrets.token_urlsafe, max_length=43, unique=True
            ),
        ),
        migrations.CreateModel(
            name="LRPDispatchData",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("data", models.JSONField(default=dict)),
                ("functionfinder", models.JSONField(default=dict)),
                (
                    "status",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="dispatch_data",
                        to="zunzun.lrpstatus",
                    ),
                ),
            ],
        ),
    ]
