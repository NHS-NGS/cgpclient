# Uploading files

!!! gel-attention ""

    Please note that this script is currently under development.

The cgpclient can be used to upload files (e.g. FASTQs) from NHS Sequencing Centres to the CGP.

We have included an example script in the [scripts](https://github.com/NHS-NGS/cgpclient/tree/main/cgpclient/scripts) directory for uploading FASTQ files generated after demultiplexing with the DRAGEN software.

!!! gel-magnify "Adapting to each GLH"

    This is an example script and may need to be modified by Sequencing Centres to make it compatible with the data being uploaded.

    Genomics England will verify, as much as possible, that uploaded files and associated resources are compatible with NGIS, but Sequencing Centres are 
    responsible for ensuring input files and parameters supplied are correct.

    If you have any questions please contact Genomics England Service Desk [here](https://jiraservicedesk.extge.co.uk/plugins/servlet/desk/category/nhsglh)

## Example data flow

Uploading FASTQ Files after demultiplexing with DRAGEN using the `upload_dragen_run.py` script.

### 1. Configure CGP Client

You will first need to configure your cgpclient. The following is the basic config required:
 
``` yaml

ods_code: XXXXXXX # your ODS code, this will be used to associate all resources with your organisation
verbose: true # print verbose output to the console, for even more detail you can use --debug or debug: true
dry_run: true # use to test the upload without uploading, you can also use the --dry_run command line argument, exclude or set to false to upload the data
override_api_base_url: true # needed when testing in non-live environments
api_host: XXXXXX # will be shared
api_key: XXXXXXX # will be shared

```

!!! gel-magnify ""

    For full details on configuration options of the cgpclient, see [configuration](../set_up/configuration.md).

### 2. Demultiplex the Sequencing Run

Use the **DRAGEN** software (version: >=`4.*.*`) to demultiplex the entire sequencing run. This will:

- Generate the FASTQ files.
- Create a file named `fastq_list.csv`.
- Create a `RunInfo.xml` metadata file.
- All these will be stored in a run folder, and we suggest you use the run folder name as the `--run_id` to uniquely identify the sequencing run.

Refer to the offical [DRAGEN documentation](https://support-docs.illumina.com/SW/DRAGEN_v39/Content/SW/DRAGEN/Inputfiles_fDG.htm) on the "FASTQ CSV File Format" for details on the `fastq_list.csv` file.

### 3. Upload FASTQ Files

Use the `upload_dragen_run.py` script with the following command:

``` python

python cgpclient/scripts/upload_dragen_run.py \
  --run_id {DRAGEN run ID}
  --run_info_file {path to DRAGEN RunInfo.xml file} (optional)
  --fastq_list_sample_id {someid} \
  --fastq_list {path to fastq list csv file from Dragen} \ 
  --ngis_participant_id {NGIS participant ID} \
  --ngis_referral_id {NGIS referral ID} \
  --config_file {path to cgpclient config file} (if you keep your config in ~/.cgpclient/config.yaml this file will be read by default and you don't need to specify here)

```

- Replace `{someid}` with the value of `RGSM` from the `fastq_list.csv` file for the sample you want to upload. If not supplied this script will use the first RGSM value found
- Repeat this command for each unique sample (as listed in the RGSM column) that has files to be uploaded.

- For a DRAGEN run the {DRAGEN run ID} should be the run folder name, e.g. `240627_M03456_0001_AHCYL3XY`. You can also optionally attach the DRAGEN `RunInfo.xml` file to the upload using the `--run_info_file` argument, in which case the file will be uploaded to the CGP and associated with the sample and run like the FASTQs.

!!! gel-magnify ""

    The script will go through each row in the `fastq_list.csv` file and upload only the files for the `<someid\>` and ignore all the others.

    
### 4. Upload Process and Resource Creation

Once executed:

- All Read 1 and Read 2 files (gz or ora compressed) for the specified sample will be uploaded to the CGP Object Store.
- Associated HL7 FHIR and GA4GH DRS resources will be created in the Clinical Data Store.
- For ora compressed files, the appropriate ora reference is determined based on the specified DRAGEN version.

!!! gel-magnify ""

    At the time of writing there is a single ora reference for humans associated with DRAGEN >= v4 which we will use by default for handling ora compressed files.

    See the [DRAGEN documentation](https://support.illumina.com/sequencing/sequencing_software/dragen-bio-it-platform/product_files.html) for more information 

### 5. Upload Results

- Large files may take time to upload, log messages will be shown on the terminal. 
- Successful uploads will return confirmation messages.
- Errors will be reported with relevant details.

### 6. Post-Upload Association

After upload:

- FASTQ files will be linked to the corresponding NGIS participant and referral.
- The NGIS pipeline will proceed once all required data has been verified.

--8<-- "includes/abbreviations.md"
