const DEV_MODE = true;
const REFERRAL_COOLDOWN = DEV_MODE ? 10 : 172800;
const EMAILJS_SERVICE_ID = "service_hm8m45q";
const EMAILJS_TEMPLATE_ID = "template_6hlgxz5";
const EMAILJS_PUBLIC_KEY = "wqGQqAkbZLnEpEOjq";

const _EMPLOYMENT_LABELS = {
  employed: "",
  student: "Student",
  graduate: "Graduate",
  laid_off: "Laid Off",
  career_break: "Career Break",
};

const _PROFILE_EMPLOYMENT_LABELS = {
  employed: "",
  student: "Student",
  graduate: "Graduate",
  laid_off: "Laid Off",
  career_break: "Career Break",
};

const _PROFILE_LABEL_TO_STATUS = {
  Student: "student",
  Graduate: "graduate",
  "Laid Off": "laid_off",
  "Career Break": "career_break",
};

const _MONTHLY_LIMIT = 3;

window.DEV_MODE = DEV_MODE;
window.REFERRAL_COOLDOWN = REFERRAL_COOLDOWN;

export { DEV_MODE, REFERRAL_COOLDOWN, EMAILJS_SERVICE_ID, EMAILJS_TEMPLATE_ID, EMAILJS_PUBLIC_KEY, _EMPLOYMENT_LABELS, _PROFILE_EMPLOYMENT_LABELS, _PROFILE_LABEL_TO_STATUS, _MONTHLY_LIMIT };
