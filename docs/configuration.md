
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