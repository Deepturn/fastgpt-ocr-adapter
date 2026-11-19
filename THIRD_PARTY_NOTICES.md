# Third-party notices

This repository contains only the FastGPT adapter code. MinerU and Marker are
separate upstream projects and are not vendored here.

## MinerU

- Project: <https://github.com/opendatalab/MinerU>
- Implemented API profiles: legacy `mineru-api` and Tasks API; see the README for tested versions
- License: review the license shipped with the selected MinerU release
- Models: Pipeline model weights have separate terms

This project does not build or distribute a MinerU model image. Users deploy
the selected official MinerU release and remain responsible for its license.

## Marker

- Project: <https://github.com/datalab-to/marker>
- Implemented API profiles: official Marker >=1.8,<2.0 and 2.0.0
- Marker 1.x and 2.x releases may use different code licenses
- Marker model weights have terms separate from the Python package

This project does not build or distribute a Marker model image. Users deploy
the selected official Marker release and remain responsible for its license.
