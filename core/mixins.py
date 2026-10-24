from django.contrib.auth.mixins import PermissionRequiredMixin


class AnyPermissionRequiredMixin(PermissionRequiredMixin):
    """Like PermissionRequiredMixin, but holding any one of ``permission_required`` is enough.

    Anonymous users go to login; signed-in users without a matching permission get a 403.
    """

    def has_permission(self):
        user = self.request.user
        return any(user.has_perm(perm) for perm in self.get_permission_required())
