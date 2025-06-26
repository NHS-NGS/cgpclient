# cgpclient: a python client library for the Clinical Genomics Platform (CGP) - Alpha

This repository contains a python client library for interacting with CGP APIs hosted in the [NHS API Platform](https://digital.nhs.uk/services/api-platform) (APIM). There are modules to enable developers to interact with various API endpoints using the HL7 FHIR, and GA4GH DRS and htsget standards, and which deal with different approaches to authentication in APIM.

The repository also includes some scripts that perform (hopefully) useful functions using these modules, and which serve as examples on how to use the client library.

__NB__ This package, and the APIs it communicates with, are under active development and are currently at the [Alpha](https://www.gov.uk/service-manual/agile-delivery/how-the-alpha-phase-works) phase of delivery. At this stage the APIs may still be subject to breaking changes, and we do not offer any SLAs etc. This code is intended to support NHS GMS partners to start to experiment with these new services and to provide feedback - please create an Issue in github, and pull requests are welcome! 

We anticipate moving to a private Beta phase in the second quarter of 2025, during which we will start to experiment with realistic data rather than the test data used so far.

## Installation

Here we assume you use conda for managing python environments, but please substitute this for your preferred tool, or you can skip this step and install the package into your main python installation.

```bash
conda create --name=cgpclient python=3.13
conda activate cgpclient
```

The environment only needs to be set up once and can then be reused.

We use `poetry` to manage dependencies etc., so if you have a fresh new environment from the command above you first need to install poetry:

```bash
pip install poetry
```

Once you have poetry installed in a suitable python environment, and if you are in the directory containing this README then the following command will install the client library and dependencies.

```bash
poetry install
```

The tests (which are still a work in progress) can be run from this directory with the command:

```bash
pytest
```

## Scripts

The scripts are available in the [cgpclient/scripts](cgpclient/scripts/) directory.

## Documentation

Full documentation is available at: [https://nhs-ngs.github.io/cgpclient/](https://nhs-ngs.github.io/cgpclient/)

Key sections include:

- [Contributing](https://nhs-ngs.github.io/cgpclient/contributing/)
- [Configuration options](https://nhs-ngs.github.io/cgpclient/set_up/configuration/)
- [NHS API Platform authentication](https://nhs-ngs.github.io/cgpclient/set_up/get_started/)
