import argparse
import logging
import sys
from pathlib import Path

import yaml  # type: ignore

from cgpclient.client import CGPClient
from cgpclient.utils import APIM_BASE_URL


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read a DRAGEN CSV format FASTQ list, upload the FASTQs and sample metadata. "
            "The sample is assumed to be a germline sample taken from blood unless a "
            "tumour ID is supplied."
        )
    )
    parser.add_argument(
        "-i",
        "--run_id",
        type=str,
        help="Unique identifier for the sequencing run that generated the FASTQs",
        required=True,
    )
    parser.add_argument(
        "-rif",
        "--run_info_file",
        type=Path,
        help="Path to the Illumina RunInfo.xml file with details of the sequencing run",
    )
    parser.add_argument(
        "-f",
        "--fastq_list",
        type=Path,
        help=(
            "Dragen FASTQ list CSV file, following the format described here: "
            "https://support-docs.illumina.com/SW/DRAGEN_v39/Content/SW/DRAGEN/Inputfiles_fDG.htm)"  # noqa: E501
        ),
        required=True,
    )
    parser.add_argument(
        "-s",
        "--fastq_list_sample_id",
        type=str,
        help=(
            "Sample identifer (RGSM) to include in the upload, "
            "if not supplied this script will use the first RGSM value found."
            "The sample is assumed be to germline unless the --tumour_id "
            "argument is supplied"
        ),
    )
    parser.add_argument(
        "-r",
        "--ngis_referral_id",
        type=str,
        help="NGIS referral identifier for the test order",
        required=True,
    )
    parser.add_argument(
        "-p",
        "--ngis_participant_id",
        type=str,
        help="NGIS participant identifier for the sample",
        required=True,
    )
    parser.add_argument(
        "-t",
        "--tumour_id",
        type=str,
        help="Histopathology or SIHMDS identifier for a tumour sample",
    )
    parser.add_argument(
        "-o",
        "--ods_code",
        type=str,
        help="ODS code for your organisation",
    )
    parser.add_argument(
        "-host",
        "--api_host",
        type=str,
        help=f"API host base URL (default {APIM_BASE_URL})",
        default=APIM_BASE_URL,
    )
    parser.add_argument(
        "-api",
        "--api_name",
        type=str,
        help="API name (e.g. genomic-data-access)",
    )
    parser.add_argument(
        "-over",
        "--override_api_base_url",
        type=bool,
        help="Override the default API base URLs in all relevant URLs",
        default=False,
    )
    parser.add_argument(
        "-k",
        "--api_key",
        type=str,
        help=(
            "NHS APIM API key from application registered in "
            "https://digital.nhs.uk/developer"
        ),
    )
    parser.add_argument(
        "-pem",
        "--private_key_pem_file",
        type=Path,
        help=(
            "Path to private key PEM file, the corresponding public key "
            "must have been shared with NHS APIM"
        ),
    )
    parser.add_argument(
        "-kid",
        "--apim_kid",
        type=str,
        help=(
            "NHS APIM Keypair Identifier (KID), must have been shared "
            "with NHS APIM (default 'test-1')"
        ),
        default="test-1",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print verbose output",
    )
    parser.add_argument(
        "-vv",
        "--debug",
        action="store_true",
        help="Print debugging output",
    )
    parser.add_argument(
        "-cfg",
        "--config_file",
        type=Path,
        help="Configuration YAML file (default ~/.cgpclient/config.yaml)",
        default=Path.home() / ".cgpclient/config.yaml",
    )
    parser.add_argument(
        "-d",
        "--dry_run",
        action="store_true",
        help="Just create the DRS and FHIR resources, don't actually upload anything",
    )

    parsed: argparse.Namespace = parser.parse_args(args)

    if parsed.config_file and parsed.config_file.is_file():
        # if we're passed a config file use it as default values
        # and then reparse
        config: dict = yaml.safe_load(parsed.config_file.read_text(encoding="utf-8"))
        parser.set_defaults(**config)
        parsed = parser.parse_args(args)

    return parsed


def main(cmdline_args: list[str]) -> None:
    args: argparse.Namespace = parse_args(cmdline_args)

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    client: CGPClient = CGPClient(
        api_host=args.api_host,
        api_name=args.api_name,
        api_key=args.api_key,
        private_key_pem=args.private_key_pem_file,
        apim_kid=args.apim_kid,
        override_api_base_url=args.override_api_base_url,
    )

    client.upload_dragen_run(
        run_id=args.run_id,
        fastq_list_csv=args.fastq_list,
        fastq_list_sample_id=args.fastq_list_sample_id,
        ngis_participant_id=args.ngis_participant_id,
        ngis_referral_id=args.ngis_referral_id,
        run_info_file=args.run_info_file,
        tumour_id=args.tumour_id,
        ods_code=args.ods_code,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
