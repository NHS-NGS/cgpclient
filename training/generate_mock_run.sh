#!/bin/bash

# CONFIGURATION
NUM_SAMPLES=2
LANE="1"
READ_LENGTH=151
READS_PER_SAMPLE=1000 

# Function to generate random DNA sequence
generate_dna_sequence() {
    local length=$1
    openssl rand -base64 $((length * 2)) | tr -d '\n' | tr 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/' 'ATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCGATCG' | head -c $length
}

# Function to generate quality scores
generate_quality_scores() {
    local length=$1
    # Generate realistic quality scores (mostly high quality with some variation)
    openssl rand -base64 $((length * 2)) | tr -d '\n' | tr 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/' 'IIIIIIIIIHHHHHHHGGGGFFFFEEEEDDDDCCCBBBAAAIII' | head -c $length
}

# Function to create FASTQ file
create_fastq() {
    local filename=$1
    local sample_id=$2
    local read_num=$3
    local num_reads=$4
    local read_length=$5
    
    for i in $(seq 1 $num_reads); do
        echo "@${sample_id}:1:${FLOWCELL_ID}:1:1101:${i}:${i} ${read_num}:N:0:ATCGATCG"
        generate_dna_sequence $read_length
        echo "+"
        generate_quality_scores $read_length
    done > "$filename"
}

# Generate identifiers
DATE=$(date +%y%m%d)
FLOWCELL_ID=$(openssl rand -hex 5 | tr '[:lower:]' '[:upper:]')
RUN_ID="${DATE}_A00123_0001_${FLOWCELL_ID}"

# Create main directory and run directory
mkdir -p "${RUN_ID}"

# Generate sample IDs for consistent use
SAMPLE_IDS=()
for i in $(seq 1 $NUM_SAMPLES); do
    SAMPLE_IDS[$i]=$((2500000 + RANDOM % 100000))
done

# Generate FASTQ files directly in run directory
for i in $(seq 1 $NUM_SAMPLES); do
    SAMPLE_ID=${SAMPLE_IDS[$i]}
    
    echo "Generating FASTQ files for sample ${SAMPLE_ID}..."
    create_fastq "${RUN_ID}/${SAMPLE_ID}_S${i}_L00${LANE}_R1_001.fastq.ora" "${SAMPLE_ID}" "1" "${READS_PER_SAMPLE}" "${READ_LENGTH}"
    create_fastq "${RUN_ID}/${SAMPLE_ID}_S1000_L00${LANE}_R2_001.fastq.ora" "${SAMPLE_ID}" "2" "${READS_PER_SAMPLE}" "${READ_LENGTH}"
done

# Create RunInfo.xml
cat > "${RUN_ID}/RunInfo.xml" << EOF
<?xml version="1.0"?>
<RunInfo>
  <Run Id="${RUN_ID}" Number="1">
    <Flowcell>${FLOWCELL_ID}</Flowcell>
    <Instrument>NovaSeq</Instrument>
    <Date>$(date +%Y-%m-%d)</Date>
    <Reads>
      <Read Number="1" NumCycles="${READ_LENGTH}" IsIndexedRead="N"/>
      <Read Number="2" NumCycles="8" IsIndexedRead="Y"/>
      <Read Number="3" NumCycles="8" IsIndexedRead="Y"/>
      <Read Number="4" NumCycles="${READ_LENGTH}" IsIndexedRead="N"/>
    </Reads>
    <FlowcellLayout LaneCount="1" SurfaceCount="2" SwathCount="3" TileCount="16"/>
  </Run>
</RunInfo>
EOF

# Create fastq_list.csv in run directory
{
    echo "RGID,RGSM,RGLB,Lane,Read1File,Read2File"
    for i in $(seq 1 $NUM_SAMPLES); do
        SAMPLE_ID=${SAMPLE_IDS[$i]}
        RGID=$(openssl rand -hex 10 | tr '[:lower:]' '[:upper:]').$(openssl rand -hex 10 | tr '[:lower:]' '[:upper:]').${LANE}
        R1_FILE="${SAMPLE_ID}_S${i}_L00${LANE}_R1_001.fastq.ora"
        R2_FILE="${SAMPLE_ID}_S1000_L00${LANE}_R2_001.fastq.ora"
        echo "${RGID},${SAMPLE_ID},UnknownLibrary,${LANE},${R1_FILE},${R2_FILE}"
    done
} > "${RUN_ID}/fastq_list.csv"

echo "Mock run created: ${RUN_ID}"