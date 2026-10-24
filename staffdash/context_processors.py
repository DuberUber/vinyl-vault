from .roles import can_use_dashboard


def staff_access(request):
    """Whether to show the Staff link in the navigation."""
    return {'show_staff_link': request.user.is_authenticated and can_use_dashboard(request.user)}
