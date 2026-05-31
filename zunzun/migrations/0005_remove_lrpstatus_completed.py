from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("zunzun", "0004_lrpstatus_state"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="lrpstatus",
            name="completed",
        ),
    ]
