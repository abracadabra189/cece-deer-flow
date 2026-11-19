# Authentication state and recovery

Login-page gating reads `/api/v1/auth/setup-status` through `core/auth/setup.ts`:
`canCreateRegularAccount` owns the signup entry and `isPasswordLoginDisabled` owns the
password form (`auth.local.password_login_enabled: false` closes password sign-in on an
externally provisioned deployment). Both treat an absent flag as permitted, so an older
Gateway — or a probe still in flight — can never hide sign-in on a deployment that allows
it; only an explicit `false` closes anything. With password login closed, one notice
replaces the form and the signup toggle and also carries `?error=…`, because a failed
external hand-off lands on `/login?error=external_login_failed` and would otherwise render
no reason at all.

`AuthProvider` publishes the query owner: user ID, confirmed logout (`null`), or
unknown auth (`undefined`). Keep auth outside `QueryClientProvider`. Its mount-local
client remounts consumers, clears the old cache and cancels queries on owner changes.
Confirmed logout unmounts consumers immediately; public/unknown routes retain an
independent client. Superseded refreshes cannot restore an earlier owner.

Transport failure leaves unknown auth eligible for the 60-second visible-tab
check. A visible `online` event revalidates unknown auth immediately, but never
authenticates on connectivity alone. Confirmed anonymous/logout and static demos
do not probe. Keep wakeups single-flight and remove listeners on unmount.
Only the current request may release its in-flight guard; confirmed user/logout
supersedes that ownership. Coalesce reconnects during a pending refresh into one
follow-up only if auth remains unknown. Success, 401/logout, account replacement
and unmount discard the deferred wake. Hidden tabs retain reconnect wakeups until
visible, bypassing the tab-switch throttle once. Keep `isLoading` in the effect
dependencies so failed requests that leave auth unchanged still drain pending wakes.

Regressions: `tests/unit/core/auth/AuthProvider-recovery.dom.test.tsx` and
`tests/e2e/auth-network-recovery.spec.ts` under `frontend/`, alongside query-owner
and artifact-draft isolation suites. Forms trim emails, never raw passwords.
