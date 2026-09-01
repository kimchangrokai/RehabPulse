# Company and project case stores

## Purpose

Each commissioned project is its own Excel workbook. Companies are directories that group those files.

## Layout

- Workbook: `data/{company}/{project}.xlsx`
- Sidecar: `data/{company}/{project}.yaml`
- Initial companies: `대신증권`, `삼성증권`
- Initial project on each: `2608계약건`
- Workbook sheets: 사건목록, 일반내용, 진행명령, 변경이력, 실행로그, 종료목록, 담당자, 메일링리스트
- No global `rehabpulse.xlsx` and no company-level mailbox file

## Case identity

- Unique inside a workbook: court + case number
- The same court + case number may exist in another project workbook
- Duplicate add inside one workbook is rejected

## TEST data

- Do not migrate the previous six seed cases
- Both initial mailing lists: `sonaba79@gmail.com`, `kimchangrok.ai@gmail.com`
