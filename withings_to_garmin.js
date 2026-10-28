const fs = require('fs');

/**
 * Converts Withings CSV data to Garmin-compatible CSV format.
 * * Logic:
 * 1. Reads the Withings CSV.
 * 2. Converts Weight (kg) to lbs.
 * 3. Calculates BMI using height (173 cm).
 * 4. Calculates Fat % from Fat mass (kg) and Weight (kg).
 * 5. Formats the date and time.
 * 6. Prepends the "Body" header required by Garmin.
 * * @param {string} inputPath - Path to the Withings CSV file.
 * @param {string} outputPath - Path where the Garmin CSV will be saved.
 * @param {number} heightCm - User height in centimeters for BMI calculation.
 */
async function convertWithingsToGarmin(inputPath, outputPath, heightCm = 173) {
    try {
        // Read the file content into memory as a string
        const data = fs.readFileSync(inputPath, 'utf8');
        
        // Simple CSV parsing (split by lines, then by comma)
        const lines = data.trim().split('\n');
        if (lines.length < 2) {
            throw new Error("Input file is empty or missing data.");
        }

        // Extract headers from the first line and find indices
        // Header looks like: Date,"Weight (kg)","Fat mass (kg)"...
        const headers = lines[0].split(',').map(h => h.replace(/"/g, '').trim());
        const idxDate = headers.indexOf('Date');
        const idxWeight = headers.indexOf('Weight (kg)');
        const idxFatMass = headers.indexOf('Fat mass (kg)');

        const outputRows = [];
        const heightMeters = heightCm / 100;

        // Process each data row (skip header)
        for (let i = 1; i < lines.length; i++) {
            // Use regex to handle potential commas inside quotes (though rare in this format)
            const row = lines[i].match(/(".*?"|[^,]+)(?=\s*,|\s*$)/g) || [];
            const cleanRow = row.map(val => val.replace(/"/g, '').trim());

            const dateStr = cleanRow[idxDate];
            const weightKg = parseFloat(cleanRow[idxWeight]);
            const fatMassKg = parseFloat(cleanRow[idxFatMass]);

            if (!dateStr || isNaN(weightKg)) continue;

            // 1. Date and Time formatting
            // Withings format: "2026-03-18 08:45:51"
            const [datePart, timePart] = dateStr.split(' ');

            // 2. Weight conversion (kg to lbs)
            // const weightLbs = (weightKg * 2.20462).toFixed(1);

            // 3. BMI Calculation: kg / (m^2)
            const bmi = (weightKg / (heightMeters * heightMeters)).toFixed(1);

            // 4. Fat percentage calculation
            let fatPercent = "0.0";
            if (!isNaN(fatMassKg) && weightKg > 0) {
                fatPercent = ((fatMassKg / weightKg) * 100).toFixed(1);
            }

            outputRows.push(`${weightKg},${bmi},${fatPercent},${datePart},${timePart}`);
        }

        // Build the final CSV content
        // Garmin requires the word "Body" on the first line
        const finalCsvContent = [
            'Body',
            'weight,bmi,fat,date,time',
            ...outputRows
        ].join('\n');

        fs.writeFileSync(outputPath, finalCsvContent);
        console.log(`Successfully converted ${outputRows.length} records to ${outputPath}`);

    } catch (err) {
        console.error("Error converting CSV:", err.message);
    }
}

// Run the script
// const inputFilename = 'withings_data.csv';
const inputFilename = 'wi_weight.csv';
const outputFilename = 'garmin_upload.csv';

// Create a dummy input file for demonstration purposes if it doesn't exist
if (!fs.existsSync(inputFilename)) {
    const dummyContent = `Date,"Weight (kg)","Fat mass (kg)","Bone mass (kg)","Muscle mass (kg)","Hydration (kg)",Comments
"2026-03-18 08:45:51",73.73,,,,,
"2026-03-17 10:46:40",72.87,13.47,2.96,56.43,41.41,
"2026-03-16 07:41:25",73.49,,,,,
"2026-03-15 08:04:17",73.68,15.28,2.92,55.47,40.57,`;
    fs.writeFileSync(inputFilename, dummyContent);
}

convertWithingsToGarmin(inputFilename, outputFilename, 173);