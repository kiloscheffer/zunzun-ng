from django.db import migrations, models


def backfill_state(apps, schema_editor):
    LRPStatus = apps.get_model("zunzun", "LRPStatus")
    LRPStatus.objects.filter(completed=True).update(state="terminal")
    LRPStatus.objects.filter(completed=False, process_id__gt=0).update(state="running")
    # completed=False + process_id=0 keeps the "initializing" default.


def reverse_backfill(apps, schema_editor):
    # No-op: completed still exists at this point. The AddField reverse drops
    # the state column.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("zunzun", "0003_alter_lrpstatus_current_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="lrpstatus",
            name="state",
            field=models.CharField(
                choices=[
                    ("initializing", "Initializing"),
                    ("running", "Running"),
                    ("terminal", "Terminal"),
                ],
                default="initializing",
                max_length=12,
            ),
        ),
        migrations.RunPython(backfill_state, reverse_backfill),
    ]
