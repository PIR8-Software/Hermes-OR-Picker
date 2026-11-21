# Changelog

## 1.1.2

Hardening release. Curated lists, custom provider copies, and the composer provider name **OR Picker** are unchanged. This release does not reconstruct or guarantee recovery of descriptions from a damaged list.

### Since 1.1.1

- Profile homes share one provider tree. A running gateway re-scans after install so OR Picker registers without a gateway restart.
- Installers refresh installer-owned provider copies in place, including a Windows real-copy fallback, and migrate known legacy pairs. Custom copies and extra files stay. A nonempty curated list is not overwritten.
- Profile-scoped install roots, including trailing or repeated separators, install at the Hermes root and still wire sibling profiles.
- Malformed curated entries are preserved. Unreadable or invalid UTF-8 input returns an error, does not report success, and does not rewrite the file.
- Selected flags are recomputed after add, remove, and reorder, including cache hits.
- The curated-file path is resolved once per operation so the dashboard writer and the provider reader agree across profile or environment changes.
- The first write creates missing parent directories. A write through a dangling symlink follows the link instead of replacing it.
- Transient upstream failures for catalog, activity, blog, credits, and analytics are not cached as empty success.
- Export and import keep order and explicit descriptions, accept legacy, object, and manifest shapes, merge additively, and reject malformed types.
- Per-model toggle and import keep ownership of in-flight work. Failed requests and late reads do not erase visible state. A changelog retry stays distinct from a no-change result.
- File locks fail closed. Atomic writes keep lock sidecars so removing a lock cannot race a new one.
- CI pins actions and the Hermes discovery commit, runs the JavaScript behavior suite, and fails the process-lifetime job if the pinned runtime is missing instead of skipping it.

Install with `install.sh` or `install.ps1` from this tag. Python API changes need a dashboard remount on the gateway host. Publishing this repository does not restart any service.
