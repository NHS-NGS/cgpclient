import argparse
import logging
import sys
from pathlib import Path

import yaml  # type: ignore
from tabulate import tabulate  # type: ignore

from cgpclient.client import CGPClient, CGPFile
from cgpclient.fhir import ClientConfig


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch details of genomic files associated with the supplied identifiers"
        )
    )
    parser.add_argument(
        "-r",
        "--referral_id",
        type=str,
        help="NGIS referral ID, e.g r30000000001",
    )
    parser.add_argument(
        "-p",
        "--participant_id",
        type=str,
        help="NGIS participant ID, e.g p12345678303",
    )
    parser.add_argument("-s", "--sample_id", type=str, help="Sample identifier")
    parser.add_argument(
        "-id",
        "--run_id",
        type=str,
        help=(
            "Unique identifier for the sequencing run that generated the FASTQs, "
            "for a DRAGEN run this should be the run folder name"
        ),
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
        "-a",
        "--all",
        action="store_true",
        help="Show all file details rather than summary",
    )
    parser.add_argument(
        "-host",
        "--api_host",
        type=str,
        help="API host base URL (default api.service.nhs.uk)",
        default="api.service.nhs.uk",
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
        "-pp",
        "--pretty_print",
        action="store_true",
        help="Pretty print JSON output",
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

    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    config: ClientConfig = ClientConfig(
        ods_code=args.ods_code,
        referral_id=args.referral_id,
        participant_id=args.participant_id,
        tumour_id=args.tumour_id,
        run_id=args.run_id,
        sample_id=args.sample_id,
    )

    client: CGPClient = CGPClient(
        api_host=args.api_host,
        api_name=args.api_name,
        api_key=args.api_key,
        private_key_pem=args.private_key_pem_file,
        apim_kid=args.apim_kid,
        override_api_base_url=args.override_api_base_url,
        config=config,
    )

    files: list[CGPFile] = client.list_files()

    short_cols: list[str] = [
        "name",
        "size",
        "content_type",
        "author_ods_code",
        "last_updated",
        "referral_id",
        "participant_id",
        "lab_sample_id",
        "run_id",
    ]

    all_cols: list[str] = short_cols + ["document_reference_id", "drs_url", "hash"]

    cols = all_cols if args.all else short_cols

    print(tabulate([[getattr(f, c) for c in cols] for f in files], headers=cols))


if __name__ == "__main__":
    main(sys.argv[1:])
