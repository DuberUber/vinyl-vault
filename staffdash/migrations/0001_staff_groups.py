from django.contrib.auth.management import create_permissions
from django.db import migrations

# Group name -> permissions ("app_label.codename"). Copied here rather than imported so the
# migration keeps working if the app code changes later.
GROUP_PERMISSIONS = {
    'Inventory': [
        'catalog.view_record', 'catalog.add_record', 'catalog.change_record', 'catalog.adjust_stock',
        'catalog.view_stockadjustment',
        'catalog.view_artist', 'catalog.add_artist', 'catalog.change_artist',
        'catalog.view_genre', 'catalog.add_genre', 'catalog.change_genre',
    ],
    'Sales': [
        'catalog.view_record', 'catalog.change_price', 'catalog.view_pricechange',
        'orders.view_order', 'orders.manage_orders',
    ],
}


def create_groups(apps, schema_editor):
    # Permissions are normally created after all migrations run (post_migrate); create them now so a
    # fresh database gets fully populated groups.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    for name, perms in GROUP_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=name)
        for perm in perms:
            app_label, codename = perm.split('.')
            group.permissions.add(Permission.objects.get(content_type__app_label=app_label, codename=codename))


def remove_groups(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(name__in=GROUP_PERMISSIONS).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        ('catalog', '0001_initial'),
        ('orders', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_groups, remove_groups),
    ]
