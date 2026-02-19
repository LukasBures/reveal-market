export const EMAIL_REGEX = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export const isValidEmail = (value: string) => EMAIL_REGEX.test(value.trim());
