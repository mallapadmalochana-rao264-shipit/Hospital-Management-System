// Run in mongosh against the hospital_management database.
// These collections store flexible clinical documents. IDs refer to SQLite rows;
// they are application-managed references, not MongoDB foreign keys.
db.createCollection("medical_records", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["patient_id", "doctor_id", "visit_date", "diagnosis"],
    properties: {
      patient_id: { bsonType: "int" }, doctor_id: { bsonType: "int" },
      visit_date: { bsonType: "string" }, diagnosis: { bsonType: "string" },
      symptoms: { bsonType: "array", items: { bsonType: "string" } },
      vitals: { bsonType: "object", properties: {
        bp: { bsonType: ["string", "null"] },
        temp: { bsonType: ["double", "int", "null"] },
        pulse: { bsonType: ["int", "long", "null"] }
      }},
      notes: { bsonType: ["string", "null"] }
    }
  }}
});
db.createCollection("prescriptions", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["patient_id", "doctor_id", "date", "medicines"],
    properties: {
      patient_id: { bsonType: "int" }, doctor_id: { bsonType: "int" },
      date: { bsonType: "string" },
      medicines: { bsonType: "array", items: { bsonType: "object",
        required: ["name", "dosage", "duration"],
        properties: { name: { bsonType: "string" }, dosage: { bsonType: "string" }, duration: { bsonType: "string" } }
      }},
      advice: { bsonType: ["string", "null"] }
    }
  }}
});
db.createCollection("lab_reports", {
  validator: { $jsonSchema: {
    bsonType: "object",
    required: ["patient_id", "doctor_id", "date", "test_name", "status"],
    properties: {
      patient_id: { bsonType: "int" }, doctor_id: { bsonType: "int" },
      date: { bsonType: "string" }, test_name: { bsonType: "string" },
      status: { enum: ["Pending", "Completed"] },
      results: { bsonType: "array", items: { bsonType: "object",
        properties: { parameter: { bsonType: "string" }, value: { bsonType: "string" },
          unit: { bsonType: "string" }, range: { bsonType: "string" } }
      }},
      remarks: { bsonType: ["string", "null"] }
    }
  }}
});
db.medical_records.createIndex({ patient_id: 1 });
db.medical_records.createIndex({ doctor_id: 1 });
db.medical_records.createIndex({ visit_date: -1 });
db.prescriptions.createIndex({ patient_id: 1 });
db.prescriptions.createIndex({ doctor_id: 1 });
db.prescriptions.createIndex({ date: -1 });
db.lab_reports.createIndex({ patient_id: 1 });
db.lab_reports.createIndex({ doctor_id: 1 });
db.lab_reports.createIndex({ date: -1 });
