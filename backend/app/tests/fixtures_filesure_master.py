"""A REAL FileSure company-master response, trimmed but never edited.

Captured from the live API for CIN U46909MH2020PLC351339 (ZEPTO LIMITED).
Every value here is exactly what the provider returned — the structure is
abridged to keep the file readable, but no field was corrected, renamed or
tidied on the way in. That is the whole point: this is the shape the
adapter has to survive, not the shape the documentation described.

Six adapter defects were found against this one payload. See
test_filesure_master_live.py.
"""

ZEPTO = {
  "cin": "U46909MH2020PLC351339",
  "company": "ZEPTO LIMITED",
  "cinHistory": [{"oldCin": "U72900MH2020PTC351339", "detectedAt": "2025-08-24T12:55:31.120Z"}],
  "nameHistory": [{"oldName": "KIRANAKART TECHNOLOGIES PRIVATE LIMITED", "detectedAt": "2025-08-24T12:55:31.120Z"}],
  "masterData": {
    "companyData": {
      "CIN": "U46909MH2020PLC351339", "company": "ZEPTO LIMITED",
      "companyType": "Company", "companyOrigin": "Indian",
      "dateOfIncorporation": "12/05/2020",
      "whetherListedOrNot": "N",
      "companyCategory": "Company limited by shares",
      "classOfCompany": "Public",
      "authorisedCapital": "207000000000",
      "paidUpCapital": "63015969430",
      "dateOfLastAGM": "08/11/2025",
      "mainDivision": "46",
      "mainDivisionDescription": "WHOLESALETRADE,EXCEPTOFMOTORVEHICLESANDMOTORCYCLES",
      "balanceSheetDate": "03/31/2025",
      "MCAMDSCompanyAddress": [{
        "streetAddress": "Hiranandani Lighthall A Wing 6  Flr",
        "addressType": "Registered Address", "city": "Mumbai",
        "state": "Maharashtra", "postalCode": "400072", "country": "India"}],
    },
    "directorData": [
      {"DIN": "01779672", "PAN": "*****0953H", "dateOfAppointment": "12/05/2020",
       "DirectorDisqualified": "N", "FirstName": "MANISH", "MiddleName": "", "LastName": "JAIN",
       "MCAUserRole": [{"cessationDate": "", "isDisqualified": "N", "role": "Director/Designated Partner",
                        "designation": "Director", "companyName": "PARASMANI ROADLINES PVT LTD",
                        "directorCategory": "Promoter", "personType": "Signatory"}]},
      {"DIN": "10904332", "PAN": "*****5805A", "dateOfAppointment": "12/24/2025",
       "DirectorDisqualified": "N", "FirstName": "AADIT", "MiddleName": "KAVIT", "LastName": "PALICHA",
       "MCAUserRole": [{"cessationDate": "", "isDisqualified": "N", "role": "Director/Designated Partner",
                        "designation": "Managing Director", "companyName": "ZEPTO LIMITED",
                        "directorCategory": "Promoter", "personType": "Signatory"}]},
      {"DIN": "ACKPJ3297Q", "PAN": "", "dateOfAppointment": "01/01/1900",
       "DirectorDisqualified": "N", "FirstName": ".", "MiddleName": "", "LastName": ".",
       "MCAUserRole": []},
      {"DIN": "", "PAN": "", "dateOfAppointment": "01/01/1900",
       "DirectorDisqualified": "N", "FirstName": ".", "MiddleName": ".", "LastName": ".",
       "MCAUserRole": []},
    ],
    "indexChargesData": [
      {"SRN": "AA8679527", "chargeId": "100684066", "chName": "ORBIS TRUSTEESHIP SERVICES PRIVATE LIMITED",
       "dateOfCreation": "07/28/2022", "dateOfSatisfaction": "06/20/2024",
       "amount": "500000000", "chargeStatus": "Closed"},
      {"SRN": "AB5257254", "chargeId": "100730684", "chName": "The Hongkong and Shanghai Banking Corporation Limited",
       "dateOfCreation": "06/01/2023", "dateOfModification": "06/25/2025", "dateOfSatisfaction": "",
       "amount": "1600000000", "chargeStatus": "Open"},
      {"SRN": "AB2415026", "chargeId": "100820756", "chName": "HDFC BANK LIMITED",
       "dateOfCreation": "11/15/2023", "dateOfSatisfaction": "",
       "amount": "500000000", "chargeStatus": "Open"},
      {"SRN": "AC5192835", "chargeId": "101336562", "chName": "IDFC FIRST BANK LIMITED",
       "dateOfCreation": "06/26/2026", "dateOfSatisfaction": "",
       "amount": "500000000", "chargeStatus": "Open"},
    ],
    "commonData": {
      "ucin": "U72900MH2020PTC351339", "company_name": "ZEPTO LIMITED",
      "incorporation_name": "KIRANAKART TECHNOLOGIES PRIVATE LIMITED",
      "status": "Active", "class_of_company": "Public",
      "company_type": "New Company (Others)", "entity_type": "Company",
      "date_of_incorporation": "2020-12-05",
      "authorised_capital": "207000000000", "paid_up_capital": "63015969430",
      "agm_date": "2025-08-11", "balance_sheet_date": "2025-03-31",
      "number_of_directors": 6, "whether_listed": False,
      "address_line1": "Hiranandani Lighthall A Wing 6  Flr",
      "city": "Mumbai", "state": "Maharashtra", "pincode": "400072",
      "nic_primary_code": "46909",
      "nic_primary_description": "Other non-specialised wholesale trade n.e.c.",
      "small_company_flag": "N",
    },
  },
}
