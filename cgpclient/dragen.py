from __future__ import annotations

import csv
import logging
import typing
from pathlib import Path

from fhir.resources.R4B.bundle import Bundle
from fhir.resources.R4B.composition import Composition
from fhir.resources.R4B.documentreference import (
    DocumentReference,
    DocumentReferenceRelatesTo,
)
from fhir.resources.R4B.procedure import Procedure
from fhir.resources.R4B.specimen import Specimen
from pydantic import BaseModel, PositiveInt

import cgpclient
import cgpclient.client
from cgpclient.fhir import (  # type: ignore
    DocumentReferenceRelationship,
    bundle_for,
    create_composition,
    create_drs_document_references,
    create_procedure,
    create_specimen,
    post_fhir_resource,
    reference_for,
)
from cgpclient.utils import CGPClientException

log = logging.getLogger(__name__)


class FastqListEntry(BaseModel):
    """A model for a row from a DRAGEN format FASTQ list CSV"""

    RGSM: str
    Read1File: Path
    RGID: str | None = None
    RGLB: str | None = None
    Lane: PositiveInt | None = None
    Read2File: Path | None = None


def resolve_path(fastq_list_csv: Path, fastq: Path):
    return (fastq_list_csv.parent / fastq).resolve()


def read_fastq_list(
    fastq_list_csv: Path, sample_id: str | None = None
) -> list[FastqListEntry]:
    """Read a DRAGEN format FASTQ list CSV file"""
    entries: list[FastqListEntry] = []
    with open(fastq_list_csv, mode="r", encoding="utf8") as file:
        for row in csv.DictReader(file):
            entry: FastqListEntry = FastqListEntry.model_validate(row)
            if sample_id is None:
                log.info("Using first RGSM found in file: %s", entry.RGSM)
                sample_id = entry.RGSM
            if entry.RGSM == sample_id:
                # resolve the FASTQ paths relative to the directory
                # containing the FASTQ list CSV (if necessary)
                entry.Read1File = resolve_path(
                    fastq_list_csv=fastq_list_csv, fastq=entry.Read1File
                )
                if entry.Read2File is not None:
                    entry.Read2File = resolve_path(
                        fastq_list_csv=fastq_list_csv, fastq=entry.Read2File
                    )

                entries.append(entry)
            else:
                log.debug("Ignoring RGSM: %s", entry.RGSM)

    log.info(
        "Read %i entries from FASTQ list file for sample: %s", len(entries), sample_id
    )
    return entries


@typing.no_type_check
def fastq_list_entry_to_document_references(
    entry: FastqListEntry,
    client: cgpclient.client.CGPClient,
) -> list[DocumentReference]:
    """Create a list of DocumentReferences for each FASTQ in a read group"""
    # Upload FASTQs using DRS

    fastq_files: list[Path] = [entry.Read1File]

    if entry.Read2File:
        fastq_files.append(entry.Read2File)

    doc_refs: list[DocumentReference] = create_drs_document_references(
        filenames=fastq_files,
        client=client,
    )

    if entry.Read2File:
        # add relationship between the paired FASTQs
        if len(doc_refs) != 2:
            raise CGPClientException("Unexpected number of DocumentReferences")

        doc_refs[0].relatesTo = [
            DocumentReferenceRelatesTo(
                code=DocumentReferenceRelationship.APPENDS,
                target=reference_for(doc_refs[1]),
            )
        ]

        doc_refs[1].relatesTo = [
            DocumentReferenceRelatesTo(
                code=DocumentReferenceRelationship.TRANSFORMS,
                target=reference_for(doc_refs[0]),
            )
        ]

    return doc_refs


@typing.no_type_check
def map_fastq_list_entries_to_bundle(
    entries: list[FastqListEntry],
    client: cgpclient.client.CGPClient,
    run_info_file: Path | None = None,
) -> Bundle:
    """Create a FHIR transaction Bundle for the entries from the FASTQ list CSV"""

    specimen: Specimen = create_specimen(client=client)

    procedure: Procedure = create_procedure(client=client)

    document_references: list[DocumentReference] = []

    for entry in entries:
        document_references.extend(
            fastq_list_entry_to_document_references(
                entry=entry,
                client=client,
            )
        )

    if run_info_file is not None:
        document_references.extend(
            create_drs_document_references(
                filenames=[run_info_file],
                client=client,
            )
        )

    composition: Composition = create_composition(
        specimen=specimen,
        procedure=procedure,
        document_references=document_references,
        client=client,
    )

    return bundle_for([composition, specimen, procedure] + document_references)


def upload_dragen_run(
    fastq_list_csv: Path,
    client: cgpclient.client.CGPClient,
    run_info_file: Path | None = None,
) -> None:
    """Convert a FASTQ list CSV into DRS objects and FHIR resources, and upload
    the FASTQs and the DRS and FHIR resources to the relevant services
    """
    entries: list[FastqListEntry] = read_fastq_list(
        fastq_list_csv=fastq_list_csv, sample_id=client.config.sample_id
    )

    if client.config.sample_id is None:
        client.config.sample_id = entries[0].RGSM

    bundle: Bundle = map_fastq_list_entries_to_bundle(
        entries=entries,
        run_info_file=run_info_file,
        client=client,
    )

    post_fhir_resource(
        resource=bundle,  # type: ignore
        client=client,
    )
