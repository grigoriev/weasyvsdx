# Security policy

## Reporting a vulnerability

Report a vulnerability privately through GitHub:
https://github.com/grigoriev/weasyvsdx/security/advisories/new
(the **Security** tab, **Report a vulnerability**). Do not open a public issue for it.

We answer within a week. The fix goes into the next release, and its release notes name it.

## Supported versions

Only the latest release gets fixes.

## Scope

The package in `src/weasyvsdx/`, the test and bench tools, the Dockerfile, the scripts and the
workflows belong to this repository. weasyvsdx hands untrusted Visio drawings to the tools of libvisio and
to emf2svg, each in a process of its own with limits. A way to make it read files, fetch URLs past the URL
fetcher of the caller, run past its limits, or exhaust memory or time of the calling process is in scope.

Vulnerabilities in upstream software (libvisio, librevenge, emf2svg, WeasyPrint, weasysvg, Pango, Python
and the development tools) belong to the upstream project. A crash of a tool that stays in its own process
is no vulnerability of weasyvsdx, but report it upstream. Tell us as well if this project is affected, so we can release a fix when the
upstream fix is out.
