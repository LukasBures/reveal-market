declare module "nodemailer" {
  export type Transporter = any;
  export function createTransport(...args: any[]): Transporter;
  const nodemailer: {
    createTransport: typeof createTransport;
  };
  export default nodemailer;
}
