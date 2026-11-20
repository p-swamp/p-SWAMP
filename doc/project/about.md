# About

## The project

p-SWAMP (Power Stability Wide Area Monitoring and Protection) is a platform for
developing and testing WAMPAC applications. It is an open source project hosted
by [LF Energy](https://lfenergy.org/), and funded by
[Statnett](https://www.statnett.no/en/).

It grew out of the research project
[NEWEPS](https://ri.diva-portal.org/smash/record.jsf?pid=diva2%3A1933825&dswid=2773),
and its first version is described in:

> H. Haugdal, S. D'Arco and K. Uhlen, "A Platform for Development and Testing of
> WAMPAC Applications based on Kafka Streaming," *2024 IEEE PES Innovative Smart
> Grid Technologies Europe (ISGT EUROPE)*, Dubrovnik, Croatia, 2024.
> [IEEE Xplore](https://ieeexplore.ieee.org/document/10863035)

The NEWEPS project also produced
[demonstration videos](https://www.youtube.com/playlist?list=PLE8zTKw5VFOGFu1mKQllDV4mm9gt1W3zd);
not everything they show is available here.

## Two applications in one repository

The repository holds two implementations side by side:

- the original **desktop application**, a single Python and Qt program, in
  `desktop/`; and
- the **web application** these pages describe: a server and a browser client,
  with the analyses as independent modules.

The web application's monitor runs the desktop application's monitoring
algorithms (islanding and line outage detection), ported to modules, over a live
simulation of the grid.

## Licence

Apache-2.0. See `LICENSE` in the repository.

Some of the data p-SWAMP uses is licensed separately and more restrictively; see
[data licensing](data-licensing.md).

## Code of conduct

Contributors follow the
[LF Projects Code of Conduct](https://lfprojects.org/policies/code-of-conduct/).
See also the LF Projects [policies](https://lfprojects.org/policies/) and
[trademark policy](https://lfprojects.org/policies/trademark-policy/).

## Contributors

The people who have contributed to p-SWAMP are on the
[Contributors](contributors.md) page. Contributions are welcome; see
[Contributing](contributing.md).

## AI tools

p-SWAMP is developed with the help of AI coding assistants, and contributions
made with them are welcome. Whoever submits a change is responsible for it as
for any other: they understand it, test it and sign it off. Parts of the code
that were largely generated and are not yet fully reviewed say so, as the
monitor's banner does. `AGENTS.md` sets out the project's conventions for
people and coding agents alike.

## Status

This is research code. It was written to support research, not as a polished,
production-ready product. It is provided as is, without warranty of any kind,
and it may contain bugs, incomplete features, or behaviour that changes between
versions. Validate its results before relying on them, especially in
operational or safety-critical settings.

We welcome feedback and bug reports, but cannot guarantee support or a response
time.
