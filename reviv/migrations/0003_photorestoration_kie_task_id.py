from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("reviv", "0002_photorestoration_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="photorestoration",
            name="kie_task_id",
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
    ]
