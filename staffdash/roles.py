"""Staff roles. The groups themselves are created by the 0001_staff_groups data migration."""

INVENTORY = 'Inventory'
SALES = 'Sales'

# Holding any one of these opens the dashboard home; each section then checks its own permission.
DASHBOARD_PERMISSIONS = ('catalog.change_record', 'catalog.change_price', 'orders.view_order')


def can_use_dashboard(user):
    return any(user.has_perm(perm) for perm in DASHBOARD_PERMISSIONS)
