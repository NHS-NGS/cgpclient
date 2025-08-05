 # Fetch Genomic Files

To see usage instructions for the CLI script you can run:

```bash
cgpclient/scripts/list_files --help
```

An example command line to fetch details for referral "r30000000001" using API key authentication:

```bash
API_KEY=NHSAPIMAPIKEY
cgpclient/scripts/list_files \
--referral_id r30000000001 \
--api_host sandbox.api.service.nhs.uk \
--api_name genomic-data-access \
--api_key $API_KEY
```

The script prints details of each genomic file found, example output:

```bash
last_updated         content_type         size  author_ods_code    referral_id    participant_id    sample_id           run_id               name
2025-07-07T10:52:13  text/fastq              2  ODS123             r12345         p12345            glh_sample_id_1234  glh_run_folder_1234  2506905-D09_L01_R2_001.fastq.ora
2025-07-07T10:52:13  application/xml         9  ODS123             r12345         p12345            glh_sample_id_1234  glh_run_folder_1234  RunInfo.xml
2025-07-07T10:52:13  text/fastq              2  ODS123             r12345         p12345            glh_sample_id_1234  glh_run_folder_1234  2506905-D09_L01_R1_001.fastq.ora
...

```


To use signed JWT authentication you can use a command line like below, assuming you have a private key PEM file and a KID as described above:

```bash
PEM_FILE=path/to/test-1.pem
API_KEY=NHSAPIMAPIKEY
cgpclient/scripts/list_files \
--referral_id r30000000001 \
--api_host internal-dev.api.service.nhs.uk \
--api_name genomic-data-access \
--api_key $API_KEY \
--private_key_pem_file $PEM_FILE \
--apim_kid test-1
```

The output format is the same for both approaches.

If you use a configuration file in the default location `~/.cgpclient/config.yaml` with appropriate arguments set, this command can be simplified to:

```bash
cgpclient/scripts/list_files -r r30000000001
```
--8<-- "includes/abbreviations.md"