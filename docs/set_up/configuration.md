# Configuration

All command-line arguments described for the scripts below can also be supplied using a YAML format configuration file. You can specify the configuration file using the `--config_file` or `-cfg` arguments.

By default, scripts will check for the existence of `~/.cgpclient/config.yaml`. If this file exists, it will be read without you needing to provide a filename.

The configuration file should contain parameters with the same names as the command-line options described for each script. Command-line arguments will take priority over values found in the configuration file.

**Important:** All files and paths used in the configuration file must be absolute, not relative paths.

**Example Configuration File (`~/.cgpclient/config.yaml`):**

```yaml
api_host: sandbox.api.service.nhs.uk
api_name: genomic-data-access
api_key: NHSAPIMAPIKEY # This is the API key from the NHS Developer Hub (not needed for sandbox).
private_key_pem: /absolute/path/to/test-1.pem # Path to your private key (see: [https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication#step-2-generate-a-key-pair](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication#step-2-generate-a-key-pair)).
apim_kid: test-1 # The key pair KID.
output_dir: /tmp/output
verbose: true
```

**Using the Configuration File:**

With this configuration file, you can run the `cgpclient/scripts/list_files` script by supplying only the referral ID:

``` bash
cgpclient/scripts/list_files -r r30000000001
```

--8<-- "includes/abbreviations.md"