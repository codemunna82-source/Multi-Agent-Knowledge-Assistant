"""A longer handbook for the labs: several sections with multi-sentence paragraphs, so parent-child context, compression and re-ranking visibly change what reaches the model."""
SECTIONS = {
    "Parental leave": ["New parents are entitled to paid parental leave. Birth mothers receive 26 weeks of fully paid leave, and partners receive 4 weeks of fully paid leave.",
                       "Leave can be taken in one block or split into two blocks within the first year. Managers should be told at least eight weeks before the planned start.",
                       "During leave, health insurance and pension contributions continue unchanged. Returning employees keep their previous role and salary band."],
    "Travel": ["All business travel must be booked through the approved agency. Economy class is required for flights shorter than six hours.",
               "Hotel stays are reimbursed up to 180 dollars per night in major cities and 120 dollars elsewhere. Meals are reimbursed up to 60 dollars per day with receipts.",
               "Travel to high-risk regions needs written approval from the security team at least two weeks in advance."],
    "Equipment": ["Every employee receives a laptop, a headset and a monitor. Laptops are replaced every four years.",
                  "Lost or stolen equipment must be reported to IT within 24 hours. Personal devices may only access company data through the managed work profile.",
                  "Departing employees return all equipment on their last working day."],
    "Learning budget": ["Each employee has an annual learning budget of 1,500 dollars for courses, books and conferences. Unused budget does not carry over.",
                        "Courses longer than five days need manager approval. Certification exam fees are reimbursed after a pass.",
                        "Employees who leave within twelve months of a course above 3,000 dollars repay a pro-rata share."],
    "Working hours": ["Core hours are 10:00 to 16:00 local time. Outside core hours employees choose their schedule in agreement with their team.",
                      "Overtime is compensated with time off in lieu within three months. On-call duty is paid at a fixed rate per week.",
                      "Public holidays follow the calendar of the employee's country of employment."],
    "Security basics": ["Passwords must be at least 14 characters and are rotated every 90 days. Multi-factor authentication is mandatory for email and the VPN.",
                        "Phishing attempts are reported with the report button in the mail client. Never share credentials, even with IT staff.",
                        "Customer data may not be copied to personal storage. Violations are handled under the disciplinary policy."],
}


EXTRA = {
    "Parental leave": ["Adoption and surrogacy are treated like birth for all leave purposes. Documentation is requested only to confirm the dates.",
                       "Employees on leave are invited to team events but never required to attend. Messages sent during leave are not expected to be answered.",
                       "A phased return of up to eight weeks at reduced hours is available at full pay. The schedule is agreed with the manager before the leave ends."],
    "Travel": ["Rail is preferred for journeys under four hours. Rental cars are allowed only when no public transport option exists.",
               "Expense reports for a trip are filed within 30 days of return. Late reports need the approval of the department head.",
               "Personal days added to a business trip are unpaid and not reimbursed. Insurance covers the business part of the trip only."],
    "Equipment": ["Accessories such as keyboards and mice can be ordered from the internal shop up to a value of 120 dollars per year. Larger requests need a business reason.",
                  "Software is installed only from the approved catalog. Requests for new tools are reviewed by IT every two weeks.",
                  "Home office furniture is not provided, but a one-time allowance of 400 dollars can be claimed after the first year."],
    "Learning budget": ["Internal training sessions are free and do not use the learning budget. A calendar of sessions is published every quarter.",
                        "Conference travel is booked under the travel policy but its ticket price counts against the learning budget. Speakers have the ticket paid by the company.",
                        "Employees are encouraged to share what they learned in a short write-up on the wiki within two weeks of a course."],
    "Working hours": ["Part-time arrangements are agreed in writing and reviewed once a year. Benefits are pro-rated by working hours.",
                      "Remote work is allowed up to three days per week with manager approval. Teams keep one common in-office day each week.",
                      "Time zones are respected when scheduling meetings. Meetings outside core hours are optional unless agreed in advance."],
    "Security basics": ["Laptops use full-disk encryption and lock after five minutes of inactivity. Updates must be installed within seven days of release.",
                        "Suspected incidents are reported to the security team within 24 hours. Reporting in good faith never leads to disciplinary action.",
                        "Guests are registered at reception and accompanied at all times. Visitor badges are collected when they leave."],
}


def handbook_md() -> bytes:
    out = ["# Company Handbook", "", "This handbook summarises the main policies that apply to all employees.", ""]
    for title, paras in SECTIONS.items():
        out += [f"## {title}", ""] + [p + "\n" for p in paras + EXTRA[title]]
    return "\n".join(out).encode()
