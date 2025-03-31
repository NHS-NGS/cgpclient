
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
--8<-- "includes/abbreviations.md"