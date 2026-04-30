"use client";

import { useEffect, useState } from "react";

export type AppLanguage = "en" | "ro";

const LANGUAGE_STORAGE_KEY = "bloodwork_os_language";
const LANGUAGE_EVENT = "bloodwork-os-language-change";

const en = {
  brand: "Bloodwork OS",

  // Common
  all: "All",
  active: "Active",
  inactive: "Inactive",
  abnormal: "Abnormal",
  activeAdmissions: "Active Admissions",
  clinicalWorkspace: "Clinical Workspace",
  doctorWorkspace: "Doctor Workspace",
  adminWorkspace: "Admin Workspace",
  patientPortal: "Patient Portal",
  myCurrentPatients: "My Current Patients",
  searchPatients: "Search Patients",
  myRecords: "My Records",
  assignments: "Assignments",
  activityLog: "Activity Log",
  department: "Department",
  hospital: "Hospital",
  admin: "Admin",
  theme: "Theme",
  language: "Language",
  english: "English",
  romanian: "Romanian",
  logout: "Log Out",
  home: "Home",
  aboutUs: "About Us",
  back: "Back",
  search: "Search",
  searching: "Searching...",
  status: "Status",
  approve: "Approve",
  deny: "Deny",
  open: "Open",
  save: "Save",
  saving: "Saving...",
  cancel: "Cancel",
  edit: "Edit",
  add: "Add",
  adding: "Adding...",
  remove: "Remove",
  removing: "Removing...",
  creating: "Creating...",

  // Common medical labels
  patient: "Patient",
  doctor: "Doctor",
  name: "Name",
  dob: "DOB",
  age: "Age",
  sex: "Sex",
  cnp: "CNP",
  patientId: "Patient ID",
  date: "Date",
  details: "Details",
  timestamp: "Timestamp",
  records: "Records",
  record: "Record",
  documents: "Documents",
  documentsLabel: "Documents",
  totalRecords: "Total Records",
  bloodwork: "Bloodwork",
  scans: "Scans",
  notes: "Notes",
  note: "Note",
  medication: "Medication",
  medications: "Medications",
  hospitalizations: "Hospitalizations",
  hospitalization: "Hospitalization",
  timeline: "Timeline",
  noDate: "No date",
  verified: "Verified",
  unverified: "Unverified",
  uploadedBy: "Uploaded by",
  openOriginal: "Open Original",
  openOriginalFile: "Open Original File",
  structuredView: "Structured View",
  viewStructuredData: "View Structured Data",
  allRecords: "All Records",
  allDocuments: "All Documents",
  scan: "Scan",

  // My Records
  loadingYourRecords: "Loading your records...",
  failedLoadRecords: "Failed to load your records.",
  failedRespondRequest: "Failed to respond to request.",
  failedOpenOriginal: "Failed to open original file.",
  doctorsWithAccess: "Doctors With Access",
  uploadMedicalDocuments: "Upload medical documents",
  uploadMedicalDocumentsDesc:
    "Add bloodwork, scans, medications, hospitalization records, or other files to your portal. Upload multiple documents at once.",
  uploadDocuments: "Upload Documents",
  myDoctors: "My Doctors",
  noDoctorsAssigned: "No doctors currently assigned.",
  doctorAccessRequests: "Doctor Access Requests",
  noDoctorAccessRequests: "No doctor access requests yet.",
  myTimeline: "My Timeline",
  myTimelineDesc:
    "A chronological view of your records and care events, sorted by the date of the document or event.",
  noTimelineActivity: "No timeline activity yet.",
  activeHospitalization: "Active hospitalization",
  dischargedHospitalization: "Discharged hospitalization",
  noRecordsInSection: "No records in this section yet.",
  recordsGroupedByUploader: "Records Grouped By Doctor / Uploader",
  unknownUploader: "Unknown uploader",
  noUploadedRecords: "No uploaded records yet.",
  bloodworkTrends: "Bloodwork Trends",
  latest: "Latest",
  previous: "Previous",
  previousLabel: "Previous",
  delta: "Delta",
  unit: "Unit",
  latestSample: "Latest sample",
  ref: "Ref",
  noNumericTrends: "No numeric bloodwork trends available yet.",

  // Doctor patients page
  loadingPatients: "Loading patients...",
  myCurrentPatientsSubtitle:
    "Your active care list with abnormal flags, latest records, and trend previews.",
  totalUnderCare: "Total Under Care",
  patientsWithAbnormalLabs: "Patients With Abnormal Labs",
  recordsAvailable: "Records Available",
  patientList: "Patient List",
  patientListDesc: "Active admissions and abnormal results are prioritized.",
  searchAllPatients: "Search All Patients",
  searchCurrentPatients: "Search current patients...",
  noActiveStay: "No active stay",
  abnormalCountLabel: "abnormal",
  latestAbnormalLabs: "Latest Abnormal Labs",
  latestRecord: "Latest Record",
  activeAdmission: "Active admission",
  abnormalLatestBloodwork: "Abnormal latest bloodwork",
  openChart: "Open Chart",
  noPatientsMatch: "No patients match this view",
  noPatientsMatchDesc: "Try changing the filter or searching all patients.",
  searchPatientsButton: "Search Patients",

  // Patient Chart
  failedLoadPatientChart: "Failed to load patient chart.",
  failedCreateEvent: "Failed to create event.",
  failedDischargeEvent: "Failed to discharge event.",
  failedCreateNote: "Failed to create note.",
  failedUploadDocument: "Failed to upload document.",
  eventTitleRequired: "Event title is required.",
  noteTitleRequired: "Note title is required.",
  noteBodyRequired: "Note body is required.",
  chooseFileFirst: "Choose a file first.",
  loadingPatientChart: "Loading patient chart...",
  needsReview: "Needs Review",
  abnormalRecordsNeedReview: "Abnormal records need review",
  abnormalRecordsNeedReviewDesc:
    "Open the marked record below to review it. This alert disappears after every abnormal record has been opened by you.",
  uploadRecord: "Upload Record",
  uploadRecordDesc:
    "Add bloodwork, scans, medications, hospital documents, or other records to this chart.",
  chooseFile: "Choose File",
  noFileSelected: "No file selected",
  saveNote: "Save Note",
  createClinicalNote: "Create Clinical Note",
  noteTitle: "Note title",
  writeYourNoteHere: "Write your note here",
  addHospitalizationEvent: "Add Hospitalization Event",
  hospitalizationTitlePlaceholder: "Title, for example: Post-op monitoring",
  careNotesPlaceholder: "Description / care notes",
  createEvent: "Create Event",
  recordsDesc: "Organized documents, notes, and uploaded clinical files.",
  abnormalResultsNeedReview: "Abnormal results · needs review",
  abnormalResultsReviewed: "Abnormal results reviewed",
  openNote: "Open Note",
  noItemsInSection: "No items in this section yet.",
  assignedDoctors: "Assigned Doctors",
  viewAll: "View All →",
  admittedCapital: "Admitted",
  discharged: "Discharged",
  discharge: "Discharge",
  noHospitalizationsRecorded: "No hospitalizations recorded yet.",

  // Document Detail
  failedLoadRecord: "Failed to load record.",
  failedSaveNote: "Failed to save note.",
  failedLinkDocument: "Failed to link document.",
  failedUnlinkDocument: "Failed to unlink document.",
  loadingRecord: "Loading record...",
  clinicalNote: "Clinical Note",
  abnormalResultsInRecord: "Abnormal results in this record",
  abnormalResultsInRecordDesc:
    "Opening this record marks it reviewed for your doctor account.",
  noteDetails: "Note Details",
  created: "Created",
  lastEdited: "Last Edited",
  writeNote: "Write note...",
  linkedRecords: "Linked Records",
  linkedRecordsEmptyPrefix: "No linked",
  linkedRecordsEmptySuffix: "yet.",
  addLinked: "Add Linked",
  noAdditionalLinkedAvailablePrefix: "No additional",
  noAdditionalLinkedAvailableSuffix: "available to link.",
  abnormalResults: "Abnormal results",
  documentDetails: "Document Details",
  reportName: "Report Name",
  reportType: "Report Type",
  lab: "Lab",
  sampleType: "Sample Type",
  referringDoctor: "Referring Doctor",
  structuredData: "Structured Data",
  test: "Test",
  value: "Value",
  reference: "Reference",
  flag: "Flag",
  noStructuredLabs: "No structured lab values found.",

  // Search Patients
  failedSearchPatients: "Failed to search patients.",
  failedRequestPatientAccess: "Failed to request patient access.",
  loadingSearch: "Loading search...",
  searchPatientsAdminSubtitle:
    "Search patients and assign or reassign doctors within your department and hospital.",
  searchPatientsDoctorSubtitle:
    "Search all patient records. Open charts you already have access to, or request permission from the patient.",
  findPatient: "Find a patient",
  findPatientDesc: "Search by full name, CNP, or internal patient identifier.",
  searchPatientsPlaceholder: "Search patients...",
  results: "Results",
  searchByNameCnpId: "Search by name, CNP, or patient ID.",
  onePatientFound: "1 patient found.",
  patientsFound: "patients found.",
  startWithSearch: "Start with a search",
  noPatientsShownUntilSearch: "No patients are shown until you search.",
  noMatchingPatients: "No matching patients",
  tryAnotherPatientSearch: "Try another spelling, patient ID, or CNP.",
  assignedTo: "Assigned to",
  noDoctorAssignedDepartment: "No doctor assigned in your department",
  activeAdmissionColon: "Active admission:",
  accessApproved: "Access approved",
  requestPending: "Request pending",
  noAccessYet: "No access yet",
  assign: "Assign",
  reassign: "Reassign",
  requestAccess: "Request Access",
  requesting: "Requesting...",
  pending: "Pending",

  // Assignments
  failedLoadAssignments: "Failed to load assignments.",
  failedUnassignDoctor: "Failed to unassign doctor.",
  failedDischargePatient: "Failed to discharge patient.",
  loadingAssignments: "Loading assignments...",
  couldNotLoadAdminUser: "Could not load admin user.",
  assignmentsSubtitlePrefix: "Manage",
  assignmentsSubtitleMiddle: "assignments at",
  scopedPatients: "Scoped Patients",
  assigned: "Assigned",
  withAbnormalLabs: "With Abnormal Labs",
  currentAssignments: "Current Assignments",
  currentAssignmentsDesc:
    "Review assigned patients, abnormal lab flags, trend previews, and active admissions.",
  searchAssignmentsPlaceholder: "Search by patient, CNP, doctor, or abnormal lab...",
  unassign: "Unassign",
  unassigning: "Unassigning...",
  discharging: "Discharging...",
  noAssignmentsMatch: "No assignments match this view",
  noAssignmentsMatchDesc:
    "Try changing the filter or searching for a patient to assign.",

  // Assign Doctor
  failedLoadAssignmentPage: "Failed to load assignment page.",
  failedAssignDoctor: "Failed to assign doctor.",
  loadingAssignmentPage: "Loading assignment page...",
  assignDoctor: "Assign Doctor",
  assignDoctorSubtitlePrefix: "Assign a doctor from",
  assignDoctorSubtitleMiddle: "at",
  backToAssignments: "Back to Assignments",
  searchDoctors: "Search Doctors",
  searchDoctorsDesc: "Only doctors from your hospital and department are shown.",
  searchDoctorsPlaceholder: "Search doctors...",
  replaceCurrentDoctor: "Replace current doctor in this department",
  alreadyAssigned: "Already Assigned",
  assigning: "Assigning...",
  assignReplace: "Assign / Replace",
  addAssignment: "Add Assignment",
  noScopedDoctorsFound: "No scoped doctors found",
  noScopedDoctorsFoundDesc:
    "Make sure doctors have the same hospital and department as this admin account.",

  // Hospitalizations
  failedLoadHospitalizations: "Failed to load hospitalizations.",
  failedCreateHospitalization: "Failed to create hospitalization.",
  failedDischargeHospitalization: "Failed to discharge hospitalization.",
  loadingHospitalizations: "Loading hospitalizations...",
  hospitalizationsTitle: "Hospitalizations",
  hospitalizationsSubtitle:
    "Admission history, active stays, and discharge events for this patient.",
  backToChart: "Back to Chart",
  hospitalizationTitleRequired: "Hospitalization title is required.",
  hospitalizationDescriptionPlaceholder: "Description / care notes",
  createHospitalization: "Create Hospitalization",
  activeHospitalizations: "Active Hospitalizations",
  pastHospitalizations: "Past Hospitalizations",
  allHospitalizations: "All Hospitalizations",
  admitted: "Admitted",
  admittedAt: "Admitted At",
  dischargedAt: "Discharged At",
  noActiveHospitalizations: "No active hospitalizations.",
  noPastHospitalizations: "No past hospitalizations.",

  // Admin Logs
  failedLoadActivityLog: "Failed to load activity log.",
  loadingActivityLog: "Loading activity log...",
  activityLogSubtitle: "All admin actions are tracked here.",
  adminActions: "Admin Actions",
  adminActionsDesc:
    "A chronological record of assignment, discharge, and access changes.",
  noActivityLogs: "No activity logs yet.",
  noActivityLogsDesc: "Admin actions will appear here once they are recorded.",
  patientLabel: "Patient",
  doctorLabel: "Doctor",

  // Public Login Chooser
  chooseYourPortal: "Choose your portal",
  signInByRoleLine1: "Sign in by role.",
  signInByRoleLine2: "Keep records structured.",
  signInByRoleLine3: "Move faster.",
  loginChooserSubtitle:
    "Choose the portal that matches your role. Each workspace is built for the exact tasks doctors, patients, and admins need.",
  doctorLogin: "Doctor Login",
  doctorLoginDesc:
    "Sign in to review charts, structured bloodwork, notes, uploads, and patient timelines.",
  personalRecords: "Personal Records",
  patientLogin: "Patient Login",
  patientLoginDesc:
    "Sign in to access your records, uploads, doctor notes, and shared medical information.",
  operationsControl: "Operations Control",
  adminLogin: "Admin Login",
  adminLoginDesc:
    "Sign in to manage users, assignments, permissions, and platform operations.",
  login: "Login",
  signUp: "Sign Up",

  // Role Login
  portalNotFound: "Portal not found",
  loginRouteNotFound: "The login route you opened does not exist.",
  backToLoginChooser: "Back to login chooser",
  doctorAccess: "Doctor access",
  patientAccess: "Patient access",
  adminAccess: "Admin access",
  doctorLoginSubtitle:
    "Sign in to the doctor workspace for patient charts, structured bloodwork, notes, hospital events, uploads, and clinical follow-up.",
  doctorLoginHelper:
    "Doctor accounts are built for chart review, uploads, documentation, verification, and ongoing patient care.",
  patientLoginSubtitle:
    "Sign in to your patient portal for records, uploads, notes, and shared clinical information.",
  patientLoginHelper:
    "Patient accounts are built for secure access to personal records, uploaded documents, and doctor-shared updates.",
  adminLoginSubtitle:
    "Sign in to the admin workspace for roles, assignments, permissions, and oversight.",
  adminLoginHelper:
    "Admin accounts are built for platform operations, user management, access control, and system visibility.",
  portalOverview: "Portal overview",
  email: "Email",
  password: "Password",
  passwordPlaceholder: "Password",
  signingIn: "Signing in...",
  loginFailed: "Login failed.",
  wrongPortalPrefix: "This account belongs to the",
  wrongPortalSuffix: "portal.",
  needNewAccount: "Need a new account?",
  goToSignupPrefix: "Go to",
  goToSignupSuffix: "signup",
  needAnotherRole: "Need another role?",
  chooseDifferentPortal: "Choose a different portal",

  // Signup
  createYourAccount: "Create your account",
  signUpByRoleLine1: "Sign up by role.",
  signUpByRoleLine2: "Start organized.",
  signUpByRoleLine3: "Work clearly.",
  signupChooserSubtitle:
    "Pick the account type that fits your role. Each path is tailored to the workflow and information that role needs.",
  doctorSignup: "Doctor Signup",
  doctorSignupDesc:
    "Create a doctor workspace for chart review, uploads, structured data, trends, and documentation.",
  patientSignup: "Patient Signup",
  patientSignupDesc:
    "Create a patient workspace for secure record access, uploads, and doctor-shared updates.",
  adminSignup: "Admin Signup",
  adminSignupDesc:
    "Create an admin workspace for roles, permissions, assignments, and system oversight.",
  signupRouteNotFound: "The signup route you opened does not exist.",
  backToSignupChooser: "Back to signup chooser",
  doctorRegistration: "Doctor registration",
  patientRegistration: "Patient registration",
  adminRegistration: "Admin registration",
  doctorSignupSubtitle:
    "Create a doctor account to manage charts, review trends, upload records, document notes, and follow patient care in one place.",
  doctorSignupHelper:
    "Doctor signups include department and hospital information so the workspace feels clinical from day one.",
  patientSignupSubtitle:
    "Create a patient account to access records, uploads, doctor-shared notes, and clinical updates securely.",
  patientSignupHelper:
    "Patient signups are built for personal access, uploads, doctor approvals, and organized records.",
  adminSignupSubtitle:
    "Create an admin account for user management, assignments, permissions, and platform oversight.",
  adminSignupHelper:
    "Admin signups are built for operations, role control, access management, and system-wide visibility.",
  fullName: "Full Name",
  fullNamePlaceholder: "Full name",
  dateOfBirth: "Date of Birth",
  maleFemalePlaceholder: "Male / Female",
  optional: "Optional",
  createPassword: "Create password",
  creatingAccount: "Creating account...",
  signupFailed: "Signup failed.",
  alreadyHaveAccount: "Already have an account?",
  goToLoginPrefix: "Go to",
  goToLoginSuffix: "login",

  // Landing / About
  clinicalRecordWorkspace: "Clinical record workspace",
  landingHeroLine1: "Clear records.",
  landingHeroLine2: "Faster care.",
  landingHeroLine3: "One secure workspace.",
  landingHeroSubtitle:
    "Bloodwork OS gives doctors, patients, and admins a cleaner way to work with structured labs, scans, notes, hospitalizations, uploads, and access control.",
  doctorPortal: "Doctor Portal",
  doctorPortalDesc:
    "Review structured bloodwork, patient charts, notes, scans, and uploaded records.",
  patientPortalDesc:
    "Access records, uploads, doctor notes, approvals, and shared updates securely.",
  adminPortal: "Admin Portal",
  adminPortalDesc:
    "Manage assignments, permissions, user roles, and access oversight.",
  aboutBloodworkOs: "About Bloodwork OS",
  aboutHeroLine1: "Clinical records,",
  aboutHeroLine2: "built for real use.",
  aboutSubtitle:
    "Bloodwork OS is designed to make medical records easier to access, structure, review, and share across doctor, patient, and admin workflows.",
  forDoctors: "For doctors",
  forDoctorsDesc:
    "Review charts, structured bloodwork, uploads, notes, and trends in one clinical workspace.",
  forPatients: "For patients",
  forPatientsDesc:
    "Access records, uploads, doctor-shared notes, and secure updates in one portal.",
  forAdmins: "For admins",
  forAdminsDesc:
    "Manage assignments, roles, permissions, and operational oversight.",
} as const;

const ro: Record<keyof typeof en, string> = {
  brand: "Bloodwork OS",

  // Common
  all: "Toate",
  active: "Active",
  inactive: "Inactive",
  abnormal: "Anormale",
  activeAdmissions: "Internări active",
  clinicalWorkspace: "Spațiu clinic",
  doctorWorkspace: "Spațiul medicului",
  adminWorkspace: "Spațiul administratorului",
  patientPortal: "Portal pacient",
  myCurrentPatients: "Pacienții mei",
  searchPatients: "Caută pacienți",
  myRecords: "Documentele mele",
  assignments: "Alocări",
  activityLog: "Jurnal de activitate",
  department: "Departament",
  hospital: "Spital",
  admin: "Administrator",
  theme: "Temă",
  language: "Limbă",
  english: "Engleză",
  romanian: "Română",
  logout: "Deconectare",
  home: "Acasă",
  aboutUs: "Despre noi",
  back: "Înapoi",
  search: "Caută",
  searching: "Se caută...",
  status: "Stare",
  approve: "Aprobă",
  deny: "Respinge",
  open: "Deschide",
  save: "Salvează",
  saving: "Se salvează...",
  cancel: "Anulează",
  edit: "Editează",
  add: "Adaugă",
  adding: "Se adaugă...",
  remove: "Elimină",
  removing: "Se elimină...",
  creating: "Se creează...",

  // Common medical labels
  patient: "Pacient",
  doctor: "Medic",
  name: "Nume",
  dob: "Data nașterii",
  age: "Vârstă",
  sex: "Sex",
  cnp: "CNP",
  patientId: "ID pacient",
  date: "Dată",
  details: "Detalii",
  timestamp: "Dată și oră",
  records: "Documente",
  record: "Document",
  documents: "Documente",
  documentsLabel: "Documente",
  totalRecords: "Total documente",
  bloodwork: "Analize de sânge",
  scans: "Investigații imagistice",
  notes: "Note",
  note: "Notă",
  medication: "Medicație",
  medications: "Medicație",
  hospitalizations: "Internări",
  hospitalization: "Internare",
  timeline: "Cronologie",
  noDate: "Fără dată",
  verified: "Verificat",
  unverified: "Neverificat",
  uploadedBy: "Încărcat de",
  openOriginal: "Deschide originalul",
  openOriginalFile: "Deschide fișierul original",
  structuredView: "Vizualizare structurată",
  viewStructuredData: "Vezi datele structurate",
  allRecords: "Toate documentele",
  allDocuments: "Toate documentele",
  scan: "Investigație",

  // My Records
  loadingYourRecords: "Se încarcă documentele tale...",
  failedLoadRecords: "Nu am putut încărca documentele tale.",
  failedRespondRequest: "Nu am putut trimite răspunsul.",
  failedOpenOriginal: "Nu am putut deschide fișierul original.",
  doctorsWithAccess: "Medici cu acces",
  uploadMedicalDocuments: "Încarcă documente medicale",
  uploadMedicalDocumentsDesc:
    "Adaugă analize, investigații imagistice, medicație, documente de internare sau alte fișiere. Poți încărca mai multe documente simultan.",
  uploadDocuments: "Încarcă documente",
  myDoctors: "Medicii mei",
  noDoctorsAssigned: "Momentan nu există medici alocați.",
  doctorAccessRequests: "Cereri de acces de la medici",
  noDoctorAccessRequests: "Nu există cereri de acces momentan.",
  myTimeline: "Cronologia mea",
  myTimelineDesc:
    "O cronologie a documentelor și evenimentelor medicale, ordonată după data documentului sau a evenimentului.",
  noTimelineActivity: "Nu există activitate în cronologie momentan.",
  activeHospitalization: "Internare activă",
  dischargedHospitalization: "Internare finalizată",
  noRecordsInSection: "Nu există documente în această secțiune.",
  recordsGroupedByUploader: "Documente grupate după medic / încărcător",
  unknownUploader: "Încărcător necunoscut",
  noUploadedRecords: "Nu există documente încărcate.",
  bloodworkTrends: "Evoluția analizelor",
  latest: "Cel mai recent",
  previous: "Anterior",
  previousLabel: "Anterior",
  delta: "Diferență",
  unit: "Unitate",
  latestSample: "Cea mai recentă probă",
  ref: "Ref.",
  noNumericTrends: "Nu există încă tendințe numerice pentru analize.",

  // Doctor patients page
  loadingPatients: "Se încarcă pacienții...",
  myCurrentPatientsSubtitle:
    "Lista pacienților aflați în îngrijirea ta, cu rezultate anormale, ultimele documente și tendințe.",
  totalUnderCare: "Total în îngrijire",
  patientsWithAbnormalLabs: "Pacienți cu analize anormale",
  recordsAvailable: "Documente disponibile",
  patientList: "Lista pacienților",
  patientListDesc: "Internările active și rezultatele anormale sunt prioritizate.",
  searchAllPatients: "Caută toți pacienții",
  searchCurrentPatients: "Caută în pacienții actuali...",
  noActiveStay: "Fără internare activă",
  abnormalCountLabel: "anormale",
  latestAbnormalLabs: "Ultimele analize anormale",
  latestRecord: "Ultimul document",
  activeAdmission: "Internare activă",
  abnormalLatestBloodwork: "Ultimele analize au valori anormale",
  openChart: "Deschide fișa",
  noPatientsMatch: "Niciun pacient nu corespunde acestei vizualizări",
  noPatientsMatchDesc: "Schimbă filtrul sau caută în toți pacienții.",
  searchPatientsButton: "Caută pacienți",

  // Patient Chart
  failedLoadPatientChart: "Nu am putut încărca fișa pacientului.",
  failedCreateEvent: "Nu am putut crea evenimentul.",
  failedDischargeEvent: "Nu am putut marca externarea.",
  failedCreateNote: "Nu am putut crea nota clinică.",
  failedUploadDocument: "Nu am putut încărca documentul.",
  eventTitleRequired: "Titlul evenimentului este obligatoriu.",
  noteTitleRequired: "Titlul notei este obligatoriu.",
  noteBodyRequired: "Conținutul notei este obligatoriu.",
  chooseFileFirst: "Alege mai întâi un fișier.",
  loadingPatientChart: "Se încarcă fișa pacientului...",
  needsReview: "De revizuit",
  abnormalRecordsNeedReview: "Documente cu rezultate anormale de revizuit",
  abnormalRecordsNeedReviewDesc:
    "Deschide documentul marcat pentru a-l revizui. Alerta dispare după ce ai deschis toate documentele cu rezultate anormale.",
  uploadRecord: "Încarcă document",
  uploadRecordDesc:
    "Adaugă analize, investigații imagistice, medicație, documente de internare sau alte fișiere în fișa pacientului.",
  chooseFile: "Alege fișier",
  noFileSelected: "Niciun fișier selectat",
  saveNote: "Salvează nota",
  createClinicalNote: "Creează notă clinică",
  noteTitle: "Titlul notei",
  writeYourNoteHere: "Scrie nota aici",
  addHospitalizationEvent: "Adaugă internare",
  hospitalizationTitlePlaceholder: "Titlu, de exemplu: monitorizare postoperatorie",
  careNotesPlaceholder: "Descriere / note clinice",
  createEvent: "Creează eveniment",
  recordsDesc: "Documente, note și fișiere clinice organizate.",
  abnormalResultsNeedReview: "Rezultate anormale · de revizuit",
  abnormalResultsReviewed: "Rezultate anormale revizuite",
  openNote: "Deschide nota",
  noItemsInSection: "Nu există elemente în această secțiune.",
  assignedDoctors: "Medici alocați",
  viewAll: "Vezi tot →",
  admittedCapital: "Internat",
  discharged: "Externat",
  discharge: "Externează",
  noHospitalizationsRecorded: "Nu există internări înregistrate.",

  // Document Detail
  failedLoadRecord: "Nu am putut încărca documentul.",
  failedSaveNote: "Nu am putut salva nota.",
  failedLinkDocument: "Nu am putut atașa documentul.",
  failedUnlinkDocument: "Nu am putut elimina documentul atașat.",
  loadingRecord: "Se încarcă documentul...",
  clinicalNote: "Notă clinică",
  abnormalResultsInRecord: "Rezultate anormale în acest document",
  abnormalResultsInRecordDesc:
    "Deschiderea acestui document îl marchează ca revizuit pentru contul tău de medic.",
  noteDetails: "Detalii notă",
  created: "Creat",
  lastEdited: "Ultima modificare",
  writeNote: "Scrie nota...",
  linkedRecords: "Documente atașate",
  linkedRecordsEmptyPrefix: "Nu există documente atașate pentru",
  linkedRecordsEmptySuffix: "momentan.",
  addLinked: "Atașează document",
  noAdditionalLinkedAvailablePrefix: "Nu există alte documente din categoria",
  noAdditionalLinkedAvailableSuffix: "disponibile pentru atașare.",
  abnormalResults: "Rezultate anormale",
  documentDetails: "Detalii document",
  reportName: "Nume raport",
  reportType: "Tip raport",
  lab: "Laborator",
  sampleType: "Tip probă",
  referringDoctor: "Medic trimițător",
  structuredData: "Date structurate",
  test: "Analiză",
  value: "Valoare",
  reference: "Interval de referință",
  flag: "Marcaj",
  noStructuredLabs: "Nu au fost găsite valori de laborator structurate.",

  // Search Patients
  failedSearchPatients: "Nu am putut căuta pacienții.",
  failedRequestPatientAccess: "Nu am putut trimite cererea de acces.",
  loadingSearch: "Se încarcă pagina de căutare...",
  searchPatientsAdminSubtitle:
    "Caută pacienți și alocă sau realocă medici în departamentul și spitalul tău.",
  searchPatientsDoctorSubtitle:
    "Caută pacienți. Deschide fișele la care ai deja acces sau cere permisiunea pacientului.",
  findPatient: "Găsește un pacient",
  findPatientDesc: "Caută după nume complet, CNP sau identificator intern.",
  searchPatientsPlaceholder: "Caută pacienți...",
  results: "Rezultate",
  searchByNameCnpId: "Caută după nume, CNP sau ID pacient.",
  onePatientFound: "1 pacient găsit.",
  patientsFound: "pacienți găsiți.",
  startWithSearch: "Începe cu o căutare",
  noPatientsShownUntilSearch: "Pacienții apar după ce faci o căutare.",
  noMatchingPatients: "Niciun pacient găsit",
  tryAnotherPatientSearch: "Încearcă altă scriere, un ID pacient sau CNP.",
  assignedTo: "Alocat către",
  noDoctorAssignedDepartment: "Niciun medic alocat în departamentul tău",
  activeAdmissionColon: "Internare activă:",
  accessApproved: "Acces aprobat",
  requestPending: "Cerere în așteptare",
  noAccessYet: "Fără acces momentan",
  assign: "Alocă",
  reassign: "Realocă",
  requestAccess: "Cere acces",
  requesting: "Se trimite...",
  pending: "În așteptare",

  // Assignments
  failedLoadAssignments: "Nu am putut încărca alocările.",
  failedUnassignDoctor: "Nu am putut elimina alocarea medicului.",
  failedDischargePatient: "Nu am putut externa pacientul.",
  loadingAssignments: "Se încarcă alocările...",
  couldNotLoadAdminUser: "Nu am putut încărca utilizatorul administrator.",
  assignmentsSubtitlePrefix: "Gestionează alocările pentru",
  assignmentsSubtitleMiddle: "la",
  scopedPatients: "Pacienți în aria ta",
  assigned: "Alocați",
  withAbnormalLabs: "Cu analize anormale",
  currentAssignments: "Alocări curente",
  currentAssignmentsDesc:
    "Revizuiește pacienții alocați, rezultatele anormale, tendințele și internările active.",
  searchAssignmentsPlaceholder: "Caută după pacient, CNP, medic sau analiză anormală...",
  unassign: "Elimină alocarea",
  unassigning: "Se elimină alocarea...",
  discharging: "Se externează...",
  noAssignmentsMatch: "Nicio alocare nu corespunde acestei vizualizări",
  noAssignmentsMatchDesc: "Schimbă filtrul sau caută un pacient pentru alocare.",

  // Assign Doctor
  failedLoadAssignmentPage: "Nu am putut încărca pagina de alocare.",
  failedAssignDoctor: "Nu am putut aloca medicul.",
  loadingAssignmentPage: "Se încarcă pagina de alocare...",
  assignDoctor: "Alocă medic",
  assignDoctorSubtitlePrefix: "Alocă un medic din",
  assignDoctorSubtitleMiddle: "la",
  backToAssignments: "Înapoi la alocări",
  searchDoctors: "Caută medici",
  searchDoctorsDesc: "Apar doar medicii din același spital și departament.",
  searchDoctorsPlaceholder: "Caută medici...",
  replaceCurrentDoctor: "Înlocuiește medicul actual din acest departament",
  alreadyAssigned: "Deja alocat",
  assigning: "Se alocă...",
  assignReplace: "Alocă / Înlocuiește",
  addAssignment: "Adaugă alocare",
  noScopedDoctorsFound: "Nu au fost găsiți medici",
  noScopedDoctorsFoundDesc:
    "Verifică dacă medicii au același spital și departament ca acest cont de administrator.",

  // Hospitalizations
  failedLoadHospitalizations: "Nu am putut încărca internările.",
  failedCreateHospitalization: "Nu am putut crea internarea.",
  failedDischargeHospitalization: "Nu am putut externa pacientul.",
  loadingHospitalizations: "Se încarcă internările...",
  hospitalizationsTitle: "Internări",
  hospitalizationsSubtitle:
    "Istoricul internărilor, internările active și externările acestui pacient.",
  backToChart: "Înapoi la fișă",
  hospitalizationTitleRequired: "Titlul internării este obligatoriu.",
  hospitalizationDescriptionPlaceholder: "Descriere / note clinice",
  createHospitalization: "Creează internare",
  activeHospitalizations: "Internări active",
  pastHospitalizations: "Internări anterioare",
  allHospitalizations: "Toate internările",
  admitted: "Internat",
  admittedAt: "Data internării",
  dischargedAt: "Data externării",
  noActiveHospitalizations: "Nu există internări active.",
  noPastHospitalizations: "Nu există internări anterioare.",

  // Admin Logs
  failedLoadActivityLog: "Nu am putut încărca jurnalul de activitate.",
  loadingActivityLog: "Se încarcă jurnalul de activitate...",
  activityLogSubtitle: "Toate acțiunile administratorilor sunt înregistrate aici.",
  adminActions: "Acțiuni administrative",
  adminActionsDesc:
    "Un istoric cronologic al alocărilor, externărilor și modificărilor de acces.",
  noActivityLogs: "Nu există acțiuni înregistrate momentan.",
  noActivityLogsDesc:
    "Acțiunile administratorilor vor apărea aici după ce sunt înregistrate.",
  patientLabel: "Pacient",
  doctorLabel: "Medic",

  // Public Login Chooser
  chooseYourPortal: "Alege portalul",
  signInByRoleLine1: "Autentificare după rol.",
  signInByRoleLine2: "Documente structurate.",
  signInByRoleLine3: "Acces mai rapid.",
  loginChooserSubtitle:
    "Alege portalul potrivit rolului tău. Fiecare spațiu este creat pentru activitățile medicilor, pacienților și administratorilor.",
  doctorLogin: "Autentificare medic",
  doctorLoginDesc:
    "Intră pentru a revizui fișe, analize structurate, note, încărcări și cronologii ale pacienților.",
  personalRecords: "Documente personale",
  patientLogin: "Autentificare pacient",
  patientLoginDesc:
    "Intră pentru a accesa documentele tale, încărcările, notele medicilor și informațiile medicale partajate.",
  operationsControl: "Administrare",
  adminLogin: "Autentificare administrator",
  adminLoginDesc:
    "Intră pentru a gestiona utilizatori, alocări, permisiuni și operațiuni ale platformei.",
  login: "Autentificare",
  signUp: "Înregistrare",

  // Role Login
  portalNotFound: "Portalul nu a fost găsit",
  loginRouteNotFound: "Ruta de autentificare nu există.",
  backToLoginChooser: "Înapoi la alegerea portalului",
  doctorAccess: "Acces medic",
  patientAccess: "Acces pacient",
  adminAccess: "Acces administrator",
  doctorLoginSubtitle:
    "Autentifică-te în spațiul medicului pentru fișe de pacient, analize structurate, note, internări, încărcări și urmărire clinică.",
  doctorLoginHelper:
    "Conturile de medic sunt gândite pentru revizuirea fișelor, încărcări, documentare, verificare și îngrijire continuă.",
  patientLoginSubtitle:
    "Autentifică-te în portalul pacientului pentru documente, încărcări, note și informații clinice partajate.",
  patientLoginHelper:
    "Conturile de pacient oferă acces securizat la documente personale, fișiere încărcate și actualizări partajate de medici.",
  adminLoginSubtitle:
    "Autentifică-te în spațiul administratorului pentru roluri, alocări, permisiuni și supraveghere.",
  adminLoginHelper:
    "Conturile de administrator sunt gândite pentru operațiuni, gestionarea utilizatorilor, controlul accesului și vizibilitate asupra sistemului.",
  portalOverview: "Despre portal",
  email: "Email",
  password: "Parolă",
  passwordPlaceholder: "Parolă",
  signingIn: "Se autentifică...",
  loginFailed: "Autentificarea a eșuat.",
  wrongPortalPrefix: "Acest cont aparține portalului",
  wrongPortalSuffix: ".",
  needNewAccount: "Ai nevoie de un cont nou?",
  goToSignupPrefix: "Mergi la înregistrare",
  goToSignupSuffix: "",
  needAnotherRole: "Ai nevoie de alt rol?",
  chooseDifferentPortal: "Alege alt portal",

  // Signup
  createYourAccount: "Creează contul",
  signUpByRoleLine1: "Înregistrare după rol.",
  signUpByRoleLine2: "Începe organizat.",
  signUpByRoleLine3: "Lucrează eficient.",
  signupChooserSubtitle:
    "Alege tipul de cont potrivit rolului tău. Fiecare traseu este adaptat informațiilor și activităților specifice.",
  doctorSignup: "Înregistrare medic",
  doctorSignupDesc:
    "Creează un spațiu pentru medic, cu fișe, încărcări, date structurate, tendințe și documentare.",
  patientSignup: "Înregistrare pacient",
  patientSignupDesc:
    "Creează un portal pentru pacient, cu acces securizat la documente, încărcări și actualizări de la medici.",
  adminSignup: "Înregistrare administrator",
  adminSignupDesc:
    "Creează un spațiu pentru administrare, cu roluri, permisiuni, alocări și supraveghere.",
  signupRouteNotFound: "Ruta de înregistrare nu există.",
  backToSignupChooser: "Înapoi la alegerea înregistrării",
  doctorRegistration: "Înregistrare medic",
  patientRegistration: "Înregistrare pacient",
  adminRegistration: "Înregistrare administrator",
  doctorSignupSubtitle:
    "Creează un cont de medic pentru a gestiona fișe, tendințe, încărcări, note și urmărirea pacienților într-un singur loc.",
  doctorSignupHelper:
    "Înregistrarea medicilor include departamentul și spitalul, pentru ca spațiul de lucru să fie util clinic din prima zi.",
  patientSignupSubtitle:
    "Creează un cont de pacient pentru acces sigur la documente, încărcări, note partajate de medici și actualizări clinice.",
  patientSignupHelper:
    "Înregistrarea pacienților este gândită pentru acces personal, încărcări, aprobări de la medici și documente organizate.",
  adminSignupSubtitle:
    "Creează un cont de administrator pentru gestionarea utilizatorilor, alocări, permisiuni și supravegherea platformei.",
  adminSignupHelper:
    "Înregistrarea administratorilor este gândită pentru operațiuni, controlul rolurilor, gestionarea accesului și vizibilitate asupra sistemului.",
  fullName: "Nume complet",
  fullNamePlaceholder: "Nume complet",
  dateOfBirth: "Data nașterii",
  maleFemalePlaceholder: "Masculin / Feminin",
  optional: "Opțional",
  createPassword: "Creează parolă",
  creatingAccount: "Se creează contul...",
  signupFailed: "Înregistrarea a eșuat.",
  alreadyHaveAccount: "Ai deja un cont?",
  goToLoginPrefix: "Mergi la autentificare",
  goToLoginSuffix: "",

  // Landing / About
  clinicalRecordWorkspace: "Platformă pentru documente medicale",
  landingHeroLine1: "Documente clare.",
  landingHeroLine2: "Îngrijire mai rapidă.",
  landingHeroLine3: "Un spațiu securizat.",
  landingHeroSubtitle:
    "Bloodwork OS ajută medicii, pacienții și administratorii să lucreze mai ușor cu analize structurate, investigații, note, internări, încărcări și acces controlat.",
  doctorPortal: "Portal medic",
  doctorPortalDesc:
    "Revizuiește analize structurate, fișe de pacient, note, investigații și documente încărcate.",
  patientPortalDesc:
    "Accesează în siguranță documente, încărcări, note de la medici, aprobări și actualizări partajate.",
  adminPortal: "Portal administrator",
  adminPortalDesc:
    "Gestionează alocări, permisiuni, roluri de utilizator și supravegherea accesului.",
  aboutBloodworkOs: "Despre Bloodwork OS",
  aboutHeroLine1: "Documente medicale,",
  aboutHeroLine2: "gândite pentru utilizare reală.",
  aboutSubtitle:
    "Bloodwork OS este creat pentru ca documentele medicale să fie mai ușor de accesat, structurat, revizuit și partajat între medici, pacienți și administratori.",
  forDoctors: "Pentru medici",
  forDoctorsDesc:
    "Revizuiește fișe, analize structurate, încărcări, note și tendințe într-un singur spațiu clinic.",
  forPatients: "Pentru pacienți",
  forPatientsDesc:
    "Accesează documente, încărcări, note de la medici și actualizări securizate într-un singur portal.",
  forAdmins: "Pentru administratori",
  forAdminsDesc:
    "Gestionează alocări, roluri, permisiuni și supraveghere operațională.",
};

const dictionaries = {
  en,
  ro,
} as const;

export type TranslationKey = keyof typeof en;

function prettifyMissingKey(key: string) {
  return key
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/^./, (char) => char.toUpperCase());
}

export function getStoredLanguage(): AppLanguage {
  if (typeof window === "undefined") return "en";

  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  return stored === "ro" ? "ro" : "en";
}

export function setStoredLanguage(language: AppLanguage) {
  localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  window.dispatchEvent(new CustomEvent(LANGUAGE_EVENT, { detail: language }));
}

export function useLanguage() {
  const [language, setLanguageState] = useState<AppLanguage>("en");

  useEffect(() => {
    setLanguageState(getStoredLanguage());

    function handleLanguageChange(event: Event) {
      const customEvent = event as CustomEvent<AppLanguage>;
      setLanguageState(customEvent.detail || getStoredLanguage());
    }

    window.addEventListener(LANGUAGE_EVENT, handleLanguageChange);
    return () => window.removeEventListener(LANGUAGE_EVENT, handleLanguageChange);
  }, []);

  function setLanguage(nextLanguage: AppLanguage) {
    setStoredLanguage(nextLanguage);
    setLanguageState(nextLanguage);
  }

  function t(key: TranslationKey | string) {
    const dictionary = dictionaries[language] as Record<string, string>;
    const fallbackDictionary = dictionaries.en as Record<string, string>;

    return dictionary[key] || fallbackDictionary[key] || prettifyMissingKey(key);
  }

  return {
    language,
    setLanguage,
    t,
  };
}
