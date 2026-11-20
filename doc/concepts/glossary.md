# Glossary

Terms used across this documentation. Most abbreviations also show their
meaning when you hover over them anywhere on the site.

CGMES
:   Common Grid Model Exchange Standard: the European profile of CIM, used by
    transmission system operators to exchange grid models.

CIM
:   Common Information Model (IEC 61970): a standard way to describe a power
    grid, its equipment and how it is connected. p-SWAMP keeps its grid model in
    CIM.

Frame
:   One snapshot of a PMU stream: every measurement of every station at one
    instant.

Frequency
:   How fast the grid's alternating current cycles, 50 times a second (50 Hz) in
    Europe. It is the same across a connected grid, and moves with the balance
    between production and consumption.

Island
:   A part of the grid that has been cut off from the rest and runs on its own,
    with a frequency of its own.

Module
:   One analysis in p-SWAMP: a small piece of Python that reads some kind of
    message and publishes another. See [Modules](../modules/index.md).

Nordic 44
:   A research model of the Nordic power grid, simplified to 44 stations.
    p-SWAMP's recordings and simulations use it.

Phasor
:   A measurement of an alternating voltage or current as a size and an angle
    (its position in the cycle), taken at a known instant.

Pipeline
:   The sources and modules an application uses, and how they connect,
    described in a file (`pipelines/<app>.toml`).

PMU
:   Phasor measurement unit: an instrument that measures phasors many times a
    second, time-stamped by GPS, so that measurements across a grid can be
    compared at the same instant.

ROCOF
:   Rate of change of frequency, in Hz per second: how fast the frequency is
    moving. A large value follows a sudden loss of production or load.

SCADA
:   Supervisory control and data acquisition: the traditional system control
    rooms use to read measurements and operate equipment, reporting every few
    seconds and not synchronised.

Source
:   A module that produces measurements rather than reading them: a recording,
    a live feed, a simulation or an archive.

TSO
:   Transmission system operator: the company running a country's or region's
    high-voltage grid (Statnett, Svenska kraftnät, Fingrid, Energinet in the
    Nordic countries).

WAMPAC
:   Wide area monitoring, protection and control: applications that watch a
    whole grid through synchronised measurements and act on what they see.
