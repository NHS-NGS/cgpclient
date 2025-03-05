# cgpclient: a python client library for the Clinical Genomics Platform (CGP)

This repository contains a python client library for interacting with CGP APIs hosted in the [NHS API Platform](https://digital.nhs.uk/services/api-platform) (APIM). There are modules to enable developers to interact with various API endpoints using the HL7 FHIR, and GA4GH DRS and htsget standards, and which deal with different approaches to authentication in APIM.

The repository also includes some scripts that perform (hopefully) useful functions using these modules, and which serve as examples on how to use the client library.

__NB__ This package, and the APIs it communicates with, are under active development and are currently at the [Alpha](https://www.gov.uk/service-manual/agile-delivery/how-the-alpha-phase-works) phase of delivery. At this stage the APIs may still be subject to breaking changes, and we do not offer any SLAs etc. This code is intended to support NHS GMS partners to start to experiment with these new services and feedback is welcome - please create an Issue in the github project. We anticipate moving to a private Beta phase in the second quarter of 2025.

## Installation

Here we assume you use conda for managing python environments, but please substitute this for your preferred tool, or you can skp this step and install the package into your main python installation.

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

The scripts described below can be found in the `cgpclient/scripts` directory.

## NHS API Platform authentication

__NB__ You don't need to use authentication when using the APIM sandbox environment.

There are currently 2 ways you can authenticate to APIs hosted in the NHS APIM that are supported in this library; [API key authentication](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-api-key-authentication), and the more secure [signed JWT authentication pattern](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication).

To use both approaches you first need to register an application in the NHS developer hub, there are 2 versions [one for production/live applications](https://digital.nhs.uk/developer), and another for [applications in development](https://dos-internal.ptl.api.platform.nhs.uk/). When creating an application you need to select which environment it is registered in, e.g. `Development`, `Integration` or `Production`. This environment needs to align with the `--api_host` parameter used for any scripts below.

To use API key authentication, once you have created an application in the appropriate environment you can search for and add the necessary APIM API to your application. For the moment, the only API this client supports is called "Genomic Data & Access Management" (GDAM). Add this API to your application, ensuring you select the one that mentions "API key authentication" (there may be multiple). In development applications this will be approved automatically, in production you will have to complete the onboarding process.

To use signed JWT authentication you will need an application and associated API key as described above, and you will additionally have to register a public key with NHS APIM and associate it with your application in the NHS developer hub. For this pattern you will also need to associate the GDAM API which mentions "signed JWT authentication" with your application. For more details on how to set up your application to use signed JWTs please refer to the detailed NHS [documentation](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication). We include a script in `cgpclient/scripts/create_apim_keys.sh` which implements step 2 of this guide, and which is described below. Once you have followed this process, either manually or using the script, then you will have the following artefacts required to run the script: an API key, a private key PEM file, and a Key Identifier (KID).

APIM has several development environments available in addition to the production environment, including `sandbox`, `internal-dev`, `int`. Please ensure you use a consistent environment for all configuration, and then supply the environment name to the script with the `--api_host` command line option (e.g. `--api_host sandbox.api.service.nhs.uk`). While we are in development we generally use `sandbox` and `internal-dev` environments for testing. This means that the NHS applications should be in the `Development` environment. To check that signed JWT auth is working you can use the `cgpclient/scripts/get_nhs_oauth_token.py` described below to try to retrieve an OAuth token.

Both authentication approaches are supported with this library and signed JWT auth is the default if the `--private_key_pem_file` and `--apim_kid` parameters are supplied, in addition to the `--api_key` parameter. To use the API key approach omit the `--private_key_pem_file` and `--apim_kid` parameters.

## Configuration options for scripts

All of the command line arguments described for the scripts below can also be supplied using a YAML format configuration file which can be supplied with the `--config_file` or `-cfg` arguments.

By default, scripts will check for the existence of `~/.cgpclient/config.yaml` and if it exists this will be read without you needing to supply a filename.

The configuration file should contain parameters with the same name as the command line options described for each script below, and arguments supplied on the command line will take priority over values found in the config file.

Note that any files/paths used in the configuration file must be absolute, not relative paths.

An example config file is:

```yaml
api_host: sandbox.api.service.nhs.uk
api_name: genomic-data-access
api_key: NHSAPIMAPIKEY # this is the API key you get from the NHS Developer Hub when registering your application (not needed for sandbox)
private_key_pem_file: /absolute/path/to/test-1.pem # this is the path to the private key you generate following the instructions here: https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication#step-2-generate-a-key-pair
apim_kid: test-1 # this is the key pair KID from the process above
output_dir: /tmp/output
verbose: true
pretty_print: true
```

Using this config file you can run the `cgpclient/scripts/fetch_genomic_files.py` script described below supplying only the referral ID, with a command like:

```bash
python cgpclient/scripts/fetch_genomic_files.py -r r30000000001
```

## Fetch details of genomic files for an NGIS referral

To see usage instructions for the CLI script you can run:

```bash
python cgpclient/scripts/fetch_genomic_files.py --help
```

An example command line to fetch details for referral "r30000000001" using API key authentication:

```bash
API_KEY=NHSAPIMAPIKEY
python cgpclient/scripts/fetch_genomic_files.py \
--ngis_referral_id r30000000001 \
--output_file genomic_files.json \
--pretty_print \
--api_host sandbox.api.service.nhs.uk \
--api_name genomic-data-access \
--api_key $API_KEY
```

The script prints JSON formatted output with details of each genomic file found to the file specified with `--output_file`, if no filename is supplied then the output will be on STDOUT. The `--pretty_print` option formats the JSON so that it is human readable. Example output shown below:

```bash
cat genomic_files.json
{
    "files": [
        {
            "ngis_referral_id": "r30000000001",
            "ngis_participant_id": "p12345678302",
            "pedigree_role": "father",
            "ngis_document_category": "VCF_small",
            "htsget_url": "https://sandbox.api.service.nhs.uk/genomic-data-access/ga4gh/htsget/v1.3/variants/analysis:multisample:a7e361c9fbabf10c0207911a05194dc0:687c0c9ab8d5504f9e40cea07ffebec2:split_joint_vcf:a884a3031864ecfb5431a2ea136603e3:1:output:r30000000001_0011_LP1000000-DNA_E11.vcf.gz"
        },
        {
            "ngis_referral_id": "r30000000001",
            "ngis_participant_id": "p12345678301",
            "pedigree_role": "proband",
            "ngis_document_category": "VCF_small",
            "htsget_url": "https://sandbox.api.service.nhs.uk/genomic-data-access/ga4gh/htsget/v1.3/variants/analysis:multisample:a7e361c9fbabf10c0207911a05194dc0:687c0c9ab8d5504f9e40cea07ffebec2:split_joint_vcf:a884a3031864ecfb5431a2ea136603e3:1:output:r30000000001_0011_LP1000000-DNA_B05.vcf.gz"
        },

...

```

To use signed JWT authentication you can use a command line like below, assuming you have a private key PEM file and a KID as described above:

```bash
PEM_FILE=path/to/test-1.pem
API_KEY=NHSAPIMAPIKEY
python cgpclient/scripts/fetch_genomic_files.py \
--ngis_referral_id r30000000001 \
--output_file genomic_files.json \
--pretty_print \
--api_host internal-dev.api.service.nhs.uk \
--api_name genomic-data-access \
--api_key $API_KEY \
--private_key_pem_file $PEM_FILE \
--apim_kid test-1
```

The output format is the same for both approaches.

If you use a configuration file in the default location `~/.cgpclient/config.yaml` with appropriate arguments set, this command can be simplified to:

```bash
python cgpclient/scripts/fetch_genomic_files.py -r r30000000001
```

## Fetch an OAuth token from the NHS OAuth server

Usage instructions:

```bash
python cgpclient/scripts/get_nhs_oauth_token.py --help
```

For development, it is useful to be able to fetch an OAuth token from the NHS APIM using the signed JWT authentication pattern. This can be done on the command line (as described [here](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication)), but is quite fiddly so we include a script that takes the necessary input parameters, interacts with the NHS OAuth server, and prints the token to STDOUT if all is correct. Per NHS policy, this token will expire in 10 minutes and you will need to refresh it for long-running applications.

```bash
PEM_FILE=path/to/test-1.pem
API_KEY=NHSAPIMAPIKEY
python cgpclient/scripts/get_nhs_oauth_token.py \
--api_host internal-dev.api.service.nhs.uk \
--api_key $API_KEY \
--private_key_pem_file $PEM_FILE \
--apim_kid test-1
```

You can use this script to set an environment variable with the token, and then use this in curl commands interacting directly with the API by using it as Bearer token in an `Authorization` header. An example is below where we use the short forms of the command line parameters:

```bash
PEM_FILE=path/to/test-1.pem
API_KEY=NHSAPIMAPIKEY
OAUTH_TOKEN=$(python cgpclient/scripts/get_nhs_oauth_token.py -pem $PEM_FILE -k $API_KEY -host internal-dev.api.service.nhs.uk -kid test-1)
curl "https://internal-dev.api.service.nhs.uk/genomic-data-access/FHIR/R4/ServiceRequest?identifier=r30000000001" -H "Authorization: Bearer $OAUTH_TOKEN"
```

If you use a configuration file in the default location `~/.cgpclient/config.yaml` with appropriate arguments set, this command can be simplified to:

```bash
OAUTH_TOKEN=$(python cgpclient/scripts/get_nhs_oauth_token.py)
```

## Create keys to use signed JWT authentication

To simplify getting set up for signed JWT authentication we provide a bash script that implements step 2 of the [NHS guidance](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication). You need to supply an identifier for the key (known as the `KID`) and a directory where you want the outputs to be stored (this defaults to the current working directory).

```bash
bash cgpclient/scripts/create_apim_keys.sh -k "test-1" -d ~/apim_keys/
```

You then need to follow the rest of the guide to register this key with APIM, and remember to keep your private key secret and don't share it with anyone.

The private key `<KID>.pem` is the file you should provide when creating signed JWTs using the scripts in this package, along with the `KID` string "test-1" above.
