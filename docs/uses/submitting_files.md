# Uploading files

Using the cgpclient FASTQ files from NHS Sequencing Centres can be uploaded to the CGP.

We have included in the [scripts](../../cgpclient/scripts/) directory an example of how this can be done for FASTQ files that are either `.gz` or `.ora` compressed
and generated after demultiplexing with the Dragen software.

!!! warning

    This is an example script and may need to be modified by Sequencing Centres to make it compatible with the data being uploaded.

    Genomics England will verify as much as possible the uploaded files and associated resources are compatible with NGIS but Sequencing Centres are 
    responsible for ensuring input files and parameters supplied are correct.

    If you have any questions please contact Genomics England Service Desk [here]()

## Example data flow

Uploading FASTQ Files after demultiplexing with Dragen using the `upload_dragen.py` script

### 1. Demultiplex the Sequencing Run

Use the **Dragen** software (version: >=`4.*.*`) to demultiplex the entire sequencing run. This process will:

- Generate the FASTQ files.
- Create a file named `fastq_list.csv` by default.

Refer to the offical [Dragen documentation](https://support-docs.illumina.com/SW/DRAGEN_v39/Content/SW/DRAGEN/Inputfiles_fDG.htm) on the "FASTQ CSV File Format" for 
details on the `fastq_list.csv` file.

### 2. Upload FASTQ Files

Use the `upload_dragen.py` script (part of the cgpclient library) with the following command:

    ```python

    upload_dragen.py --dragen-version v4.3.13 --fastq_list fastq_list.csv --fastq_list_sample_id <someid> --ngis_participant_id p1234

    ```

- Replace <someid\> with the value of `RGSM` from the `fastq_list.csv` file for the sample you want to upload.
- Repeat this command for each unique sample (as listed in the RGSM column) that has files to be uploaded.

???+ info

    The script will go through each row in the `fastq_list.csv` file and upload only the files for the "<someid\>" and ignore all the others.

    
### 3. Upload Process and Resource Creation

Once executed:

- All Read 1 and Read 2 files (gz or ora compressed) for the specified sample will be uploaded to the CGP Object Store.

- Associated HL7 FHIR and GA4GH DRS resources will be created in the Clinical Data Store.

- For ora compressed files, the appropriate ora reference is determined based on the specified Dragen version.

???+ info

    At the time of writing there is a single ora reference for humans associated with Dragen >= v4 which we will use by default for handling
    ora compressed files.

    See the [Dragen documentation](https://support.illumina.com/sequencing/sequencing_software/dragen-bio-it-platform/product_files.html) for more information 

### 4. Upload Results

- Successful uploads will return confirmation messages.
- Errors will be reported with relevant details.

### 5. Post-Upload Association

After upload:

- FASTQ files will be linked to the corresponding NGIS participant and referral.
- The NGIS pipeline will proceed once all required data has been verified.

--8<-- "includes/abbreviations.md"
