const fs = require('fs');
const { parse } = require('csv-parse');
const { stringify } = require('csv-stringify');

// async function convertCsvFormat(inputFilename = 'format_a.csv', outputFilename = 'format_b.csv') {
    
//     const inputFilePath = inputFilename;
//     const outputFilePath = outputFilename;

//     try {
//         // Read the input CSV file
//         const records = await new Promise((resolve, reject) => {
//             const records = [];
//             fs.createReadStream(inputFilePath)
//                 .pipe(parse({
//                     columns: true, // Treat the first row as column names
//                     skip_empty_lines: true,
//                     trim: true, // Trim whitespace from values
//                 }))
//                 .on('data', (record) => records.push(record))
//                 .on('end', () => resolve(records))
//                 .on('error', (err) => reject(err));
//         });

//         const outputRecords = [];

//         for (const recordA of records) {
//             const dateStr = recordA.Date;
//             const weightKgStr = recordA['Weight (kg)'];
//             const fatMassKgStr = recordA['Fat mass (kg)'];

//             // Skip rows where essential data is missing
//             if (!dateStr || !weightKgStr) {
//                 console.warn(`Skipping row due to missing Date or Weight (kg): ${JSON.stringify(recordA)}`);
//                 continue;
//             }

//             let dtObject;
//             try {
//                 dtObject = new Date(dateStr);
//                 if (isNaN(dtObject.getTime())) {
//                     throw new Error("Invalid date format");
//                 }
//             } catch (error) {
//                 console.warn(`Skipping row due to invalid date format '${dateStr}': ${error.message}`);
//                 continue;
//             }

//             const dateB = dtObject.toISOString().split('T')[0]; // YYYY-MM-DD
//             const timeB = dtObject.toTimeString().split(' ')[0]; // HH:MM:SS

//             let weightLbs = 0.0;
//             if (weightKgStr) {
//                 try {
//                     const weightKg = parseFloat(weightKgStr);
//                     weightLbs = weightKg * 2.20462; // Convert kg to lbs
//                 } catch (error) {
//                     console.warn(`Warning: Could not convert weight '${weightKgStr}' to number. Using 0.0.`);
//                 }
//             }

//             let fatPercent = 0.0;
//             if (fatMassKgStr && weightKgStr) {
//                 try {
//                     const fatMassVal = parseFloat(fatMassKgStr);
//                     const weightVal = parseFloat(weightKgStr);
//                     if (!isNaN(fatMassVal) && !isNaN(weightVal) && weightVal > 0) {
//                         fatPercent = (fatMassVal / weightVal) * 100;
//                     }
//                 } catch (error) {
//                     console.warn(`Warning: Could not calculate fat percent for fat '${fatMassKgStr}' or weight '${weightKgStr}'. Using 0.0.`);
//                 }
//             }

//             // BMI is not derivable from the given data without height, so it remains 0.0
//             const bmiB = 0.0;

//             outputRecords.push({
//                 weight: weightLbs.toFixed(1),
//                 bmi: bmiB.toFixed(1),
//                 fat: fatPercent.toFixed(1),
//                 date: dateB,
//                 time: timeB,
//             });
//         }

//         // Define the columns for the output CSV
//         const columns = [
//             'weight',
//             'bmi',
//             'fat',
//             'date',
//             'time',
//         ];

//         // Write the transformed data to the output CSV file
//         await new Promise((resolve, reject) => {
//             stringify(outputRecords, { header: true, columns: columns })
//                 .pipe(fs.createWriteStream(outputFilePath))
//                 .on('finish', () => resolve())
//                 .on('error', (err) => reject(err));
//         });

//         console.log(`Conversion complete! '${inputFilename}' has been converted to '${outputFilename}'.`);

//     } catch (error) {
//         console.error(`Error during CSV conversion: ${error.message}`);
//     }
// }

// // --- Demonstration ---
// // 1. Create a dummy 'format_a.csv' file for testing
// // const dummyFormatAContent = `Date,"Weight (kg)","Fat mass (kg)","Bone mass (kg)","Muscle mass (kg)","Hydration (kg)",Comments
// // "2025-09-20 10:40:06",73.57,14.43,2.95,56.18,41.17,
// // "2025-09-19 17:45:16",74.73,13.86,3.03,57.83,42.60,
// // "2025-09-19 07:25:57",75.71,,,,,
// // "2025-09-18 07:14:17",74.25,16.45,2.90,54.88,40.20,
// // "2025-09-17 07:17:59",73.92,15.85,2.91,55.15,40.36,
// // "2025-09-16 07:15:28",74.17,16.35,2.90,54.91,40.21,
// // "2025-09-15 13:43:39",74.00,14.72,2.96,56.31,41.28,
// // "2025-09-15 07:21:00",75.59,16.24,2.96,56.37,41.36,
// // "2025-09-11 07:12:41",72.31,15.38,2.86,54.06,39.45,
// // "2025-09-10 21:53:19",73.01,14.69,2.91,55.40,40.52,
// // "2025-09-10 07:06:23",72.94,16.02,2.86,54.04,39.50,
// // "2025-09-09 18:32:40",72.77,13.55,2.95,56.25,41.26,
// // "2025-09-09 07:08:36",72.66,15.81,2.86,53.98,39.43,
// // "2025-09-08 19:29:45",72.68,14.64,2.90,55.12,40.29,
// // "2025-09-08 07:08:14",73.86,16.48,2.88,54.48,39.89,
// // "2025-09-07 09:47:31",75.75,16.43,2.96,56.34,41.34,
// // "2025-09-05 11:26:06",73.88,15.21,2.93,55.73,40.80,
// // "2025-09-04 07:02:24",73.25,16.76,2.85,53.62,39.26,
// // "2025-09-03 07:07:04",74.09,16.73,2.88,54.46,39.90,
// // `;

// // fs.writeFileSync('format_a.csv', dummyFormatAContent);

// // 2. Run the conversion
// // convertCsvFormat('format_a.csv', 'format_b.csv')
// //     .then(() => {
// //         console.log("Node.js CSV conversion script finished.");
// //         // Optional: Read and print the output file to verify
// //         // const outputContent = fs.readFileSync('format_b.csv', 'utf8');
// //         // console.log("\n--- Content of format_b.csv ---");
// //         // console.log(outputContent);
// //     })
// //     .catch(error => {
// //         console.error("An error occurred:", error);
// //     });


function main() {
    console.log('Hello world');

}

main();