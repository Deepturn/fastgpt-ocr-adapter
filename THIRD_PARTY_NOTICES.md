# Third-party notices

This repository contains only the FastGPT adapter code. MinerU and Marker are
separate upstream projects and are not vendored here.

## MinerU

- Project: <https://github.com/opendatalab/MinerU>
- Verified adapter target: MinerU 3.4.4, `mineru-api`
- License: review the license shipped with the selected MinerU release
- Models: Pipeline model weights have separate terms

The optional MinerU image installs the official `mineru[pipeline]==3.4.4`
package and downloads its Pipeline models. Review both the code and model
licenses before providing a commercial service.

## Marker

- Project: <https://github.com/datalab-to/marker>
- Verified adapter targets: official Marker 1.8-1.10 and 2.0.0 API profiles
- Marker 1.x and 2.x releases may use different code licenses
- Marker model weights have terms separate from the Python package

This project does not build or distribute a Marker model image. Users deploy
the selected official Marker release and remain responsible for its license.
