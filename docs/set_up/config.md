# Configuration

## Using a Configuration File
All command-line arguments for the CGP scripts can also be specified in a YAML configuration file. Use the `--config_file` or `-cfg` flag to provide the path to this file.

By default, the scripts will look for a configuration file at `~/.cgpclient/config.yaml`. If this file exists, it will be used automatically—no need to specify it explicitly.

Settings in the configuration file should use the same parameter names as the corresponding command-line arguments.

!!! gel-question "Note"
    Command-line arguments always override values specified in the configuration file.

    All file and directory paths in the configuration file must be absolute paths—relative paths are not supported.


## Example Configuration File (`~/.cgpclient/config.yaml`)

```yaml
api_host: sandbox.api.service.nhs.uk
api_name: genomic-data-access
api_key: NHSAPIMAPIKEY  # API key from the NHS Developer Hub (not required for sandbox)
private_key_pem_file: /absolute/path/to/test-1.pem  # Path to your private key file
apim_kid: test-1  # Key ID (KID) associated with the key pair
output_dir: /tmp/output  # Directory for output files
verbose: true  # Enable verbose logging
pretty_print: true  # Format output for readability
```
See [how to generate a key pair](https://digital.nhs.uk/developer/guides-and-documentation/security-and-authorisation/application-restricted-restful-apis-signed-jwt-authentication#step-2-generate-a-key-pair)


## Running a Script with Configuration

Once your config file is set up, you can run a script with minimal command-line arguments. For example:

``` bash
python cgpclient/scripts/fetch_genomic_files.py -r r30000000001
```

In this example, all other required options will be loaded from your configuration file.


--8<-- "includes/abbreviations.md"