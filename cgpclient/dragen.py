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

from cgpclient.fhir import (  # type: ignore
    CGPFHIRService,
    DocumentReferenceRelationship,
    FHIRConfig,
    ProcedureStatus,
    bundle_for,
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
    fhir_service: CGPFHIRService,
) -> list[DocumentReference]:
    """Create a list of DocumentReferences for each FASTQ in a read group"""
    # Upload FASTQs using DRS

    fastq_files: list[Path] = [entry.Read1File]

    if entry.Read2File:
        fastq_files.append(entry.Read2File)

    doc_refs: list[DocumentReference] = fhir_service.create_drs_document_references(
        filenames=fastq_files
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
def create_germline_sample(fhir_config: FHIRConfig) -> Specimen:
    logging.info("Creating Specimen resource for germline blood sample")

    return Specimen(
        id=create_uuid(),
        identifier=[fhir_config.sample_identifier],
        subject=fhir_config.participant_reference,
        request=[fhir_config.referral_reference],
        extension=[
            Extension(
                url="https://fhir.hl7.org.uk/StructureDefinition/Extension-UKCore-SampleCategory",  # noqa: E501
                valueCodeableConcept=CodeableConcept(
                    coding=[
                        Coding(
                            system="https://fhir.hl7.org.uk/CodeSystem/UKCore-SampleCategory",  # noqa: E501
                            code="germline",
                            display="Germline",
                        )
                    ]
                ),
            )
        ],
        type=CodeableConcept(
            coding=[
                Coding(
                    system="http://snomed.info/sct",
                    code="445295009",
                    display="Blood specimen with EDTA",
                )
            ]
        ),
    )


@typing.no_type_check
def create_tumour_sample(fhir_config: FHIRConfig) -> Specimen:
    logging.info("Creating Specimen resource for tumour sample")

    return Specimen(
        id=create_uuid(),
        identifier=[
            fhir_config.sample_identifier,
            fhir_config.tumour_identifier,
        ],
        subject=fhir_config.participant_reference,
        request=[fhir_config.referral_reference],
        extension=[
            Extension(
                url="https://fhir.hl7.org.uk/StructureDefinition/Extension-UKCore-SampleCategory",  # noqa: E501
                valueCodeableConcept=CodeableConcept(
                    coding=[
                        Coding(
                            system="https://fhir.hl7.org.uk/CodeSystem/UKCore-SampleCategory",  # noqa: E501
                            code="solid-tumour",
                            display="Solid Tumour",
                        )
                    ]
                ),
            )
        ],
    )


def create_specimen(fhir_config: FHIRConfig) -> Specimen:
    if fhir_config.tumour_id is not None:
        return create_tumour_sample(fhir_config=fhir_config)
    return create_germline_sample(fhir_config=fhir_config)


@typing.no_type_check
def create_procedure(fhir_config: FHIRConfig) -> Procedure:
    return Procedure(
        id=create_uuid(),
        identifier=[fhir_config.run_identifier],
        code=CodeableConcept(
            coding=[
                Coding(
                    code="461571000124105",
                    system="http://snomed.info/sct",
                    display="Whole genome sequencing",
                )
            ]
        ),
        subject=fhir_config.participant_reference,
        performer=[ProcedurePerformer(actor=fhir_config.org_reference)],
        basedOn=[fhir_config.referral_reference],
        status=ProcedureStatus.COMPLETED,
    )


@typing.no_type_check
def map_entries_to_bundle(
    entries: list[FastqListEntry],
    fhir_service: CGPFHIRService,
    run_info_file: Path | None = None,
) -> Bundle:
    """Create a FHIR transaction Bundle for the entries from the FASTQ list CSV"""

    specimen: Specimen = create_specimen(fhir_config=fhir_service.config)

    procedure: Procedure = create_procedure(fhir_config=fhir_service.config)

    document_references: list[DocumentReference] = []

    for entry in entries:
        document_references.extend(
            fastq_list_entry_to_document_references(
                entry=entry,
                fhir_service=fhir_service,
            )
        )

    if run_info_file is not None:
        document_references.extend(
            fhir_service.create_drs_document_references(filenames=[run_info_file])
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
    fhir_service: CGPFHIRService,
    run_info_file: Path | None = None,
) -> None:
    """Convert a FASTQ list CSV into DRS objects and FHIR resources, and upload
    the FASTQs and the DRS and FHIR resources to the relevant services
    """
    fhir_config = fhir_service.config
    entries: list[FastqListEntry] = read_fastq_list(
        fastq_list_csv=fastq_list_csv, sample_id=fhir_config.sample_id
    )

    if fhir_config.sample_id is None:
        fhir_config.sample_id = entries[0].RGSM

    bundle: Bundle = map_entries_to_bundle(
        entries=entries, run_info_file=run_info_file, fhir_service=fhir_service
    )

    fhir_service.post_fhir_resource(resource=bundle)
