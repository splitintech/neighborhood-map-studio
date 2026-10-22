# Daytona runtime

The release image contains the built `frontend/dist` bundle and a small
FastAPI entrypoint. `start.sh` binds the application to port `3000`; it does
not accept a command from a request or execute user supplied shell text. The
application uses Supabase for durable state and assets, so a stopped sandbox
does not contain the source of truth.

Daytona control-plane tooling is isolated in `requirements-daytona.txt`. The
SDK is pinned to `0.225.0` because its `httpx` and `anyio` requirements must
not be mixed into the existing BFF environment.

## Provisioning

Set a pinned snapshot name and run the operator script from an isolated Python
environment. The default is a JSON dry run:

```sh
export DAYTONA_MAP_STUDIO_SNAPSHOT=map-studio-release-20261020
python scripts/daytona-provision.py
```

The script will only call Daytona when `--apply` is supplied. Applying requires
`DAYTONA_API_KEY`, the snapshot name, and all server-only `MAP_STUDIO_*`
application settings: `ORIGIN`, GitHub client ID/secret, session secret,
Supabase URL, and Supabase service-role key. Only the explicit application
allowlist is forwarded to a newly created sandbox; values are never printed.
The control-plane key is never forwarded to the app.

It reuses the one fixed sandbox name, verifies the existing snapshot, OAuth
origin, and application port before reuse, starts only stopped/paused states,
rejects terminal/error states, runs a local `/healthz` check on the configured
port, and strips preview query tokens before returning the URL. A failed lookup
is not silently treated as a create; only a Daytona not-found response permits
creation. The runtime port is fixed at 3000. Startup is bounded to 60 seconds
and idle auto-stop is 15 minutes.
If an existing sandbox has the wrong snapshot or origin, stop/delete it from
the Daytona dashboard and recreate it with the desired release and fixed
OAuth origin; the script does not mutate those identity settings in place.

```sh
DAYTONA_API_KEY='…' \
MAP_STUDIO_ORIGIN='https://studio.example' \
MAP_STUDIO_GITHUB_CLIENT_ID='…' \
MAP_STUDIO_GITHUB_CLIENT_SECRET='…' \
MAP_STUDIO_SESSION_SECRET='at-least-32-random-characters' \
MAP_STUDIO_SUPABASE_URL='https://project.supabase.co' \
MAP_STUDIO_SUPABASE_SERVICE_ROLE_KEY='…' \
  python scripts/daytona-provision.py --apply
```

The reported 100-dollar monthly value is an operator cost cap and the expected
200 hours is an estimate. Neither is a billing guarantee or a Daytona quota;
the script reports `enforcedByScript: false` so this cannot be mistaken for a
cost control. Set `DAYTONA_MAP_STUDIO_BUDGET_CAP_DOLLARS` and
`DAYTONA_MAP_STUDIO_EXPECTED_HOURS` to change the displayed operator estimate.

The running application does not wake its own stopped sandbox. A scheduled
operator job, explicit control-plane call, or the Daytona dashboard must run
the provisioning command before opening the preview after auto-stop.

## Preview transport and OAuth

The sandbox is private by default. Daytona private previews require the
`X-Daytona-Preview-Token` header. A normal OAuth browser redirect does not
reliably preserve that header, and a signed preview URL can change the origin
used by the OAuth callback. The app therefore must be authenticated at the
application layer before a public transport is enabled. Every private API and asset request enforces the owner's GitHub session. The
static login shell contains no private data. Public transport does not make
drafts or originals public.

After the parent application has configured the fixed OAuth callback/origin and
owner authorization, an operator may explicitly opt in:

```sh
MAP_STUDIO_PUBLIC_TRANSPORT_AUTH_CONFIGURED=1 \
DAYTONA_API_KEY='…' \
MAP_STUDIO_ORIGIN='https://studio.example' \
MAP_STUDIO_GITHUB_CLIENT_ID='…' \
MAP_STUDIO_GITHUB_CLIENT_SECRET='…' \
MAP_STUDIO_SESSION_SECRET='at-least-32-random-characters' \
MAP_STUDIO_SUPABASE_URL='https://project.supabase.co' \
MAP_STUDIO_SUPABASE_SERVICE_ROLE_KEY='…' \
python scripts/daytona-provision.py --apply --public-transport
```

The guard is deliberate: setting a Daytona `public` flag alone is never an
authentication boundary. The public manifest path remains separate from the
owner/editor application and the app never starts a sandbox for a public map
request.

## Snapshot release

CI builds the image. Snapshot creation accepts only a registry reference with
an immutable, exactly 64-character hexadecimal `@sha256:` digest, allocates
1 CPU and 1 GiB memory, and uses the fixed `/opt/map-studio/start.sh`
entrypoint. No source checkout, API key, Supabase secret, or OAuth credential
is copied into a snapshot:

```sh
python scripts/create-snapshot.py \
  --name map-studio-release-20261020 \
  --image ghcr.io/splitintech/neighborhood-map-studio@sha256:<digest>
```

Add `--apply` only from the isolated Daytona SDK environment with
`DAYTONA_API_KEY` present. The image digest and snapshot name should be
recorded by the release operator alongside the CI build SHA.

## Release image workflow

After verification passes, an operator can run `.github/workflows/neighborhood-map-studio-image.yml` on the reviewed commit. It builds the Linux image and pushes a commit tag to GHCR, recording the immutable digest in the run summary. The workflow does not create sandboxes or embed runtime credentials. Configure Daytona's registry access to that GHCR package (or explicitly make the package publicly pullable) before creating the snapshot. Registry access and a successful image build must be verified in the target account; local source tests alone do not establish them.
