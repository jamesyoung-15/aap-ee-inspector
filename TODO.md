# Todo

## Podman + Docker compatibility

Right now we only support Podman, perhaps an option for Docker as well? Commands should be compatible.

## Filtered/Single EE Report

~~It would be nice to also support running the report on a single EE, or perhaps a config that says I want report on ["EE-1", "EE-2"], rather than everything.~~

Done: `aap-ee-inspect` and `aap-ee-report` both accept `--only "PATTERN[,PATTERN...]"` (glob patterns matched against EE names). See docs/README.md.

## Optional: Pip list support

It would be nice feature to opt-in to view dependencies via `pip list`, however this is likely going to be very large so worth noting, flagged as nice-to-have feature later on.

## Optional: Run Mode that Skips Existing Generated EEs

Personally, I'd like to run this on a schedule (say bi-weekly). Honestly it's very unlikely that the EE themselves will change, so perhaps a run-mode that only generates EEs not on our outputs or something, that way it only checks for new EEs and avoids having to wait super long each time. However this is a very nice-to-have feature again, the [Filtered/Single EE](#filteredsingle-ee-report) could cover this for my use case so perhaps not needed.
