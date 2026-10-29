# Standalone release setup

Publication starts disabled behind repository variable `IMAGE_PUBLISHING_ENABLED=true`. The migration does not publish packages or images, deploy services, configure credentials, or create release tags.

For image publishing, review the manual GHCR workflow and configure deployment separately. The React frontend is private; this repository is distributed as an application/container, not a single npm library.

Historical source copies are not release authorities. Product releases originate here after repository-specific configuration. See README for operational limits.
