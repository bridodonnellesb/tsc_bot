import { AskResponse, Citation } from "../../api";
import { cloneDeep } from "lodash";

export type ParsedAnswer = {
    citations: Citation[];
    markdownFormatText: string;
};

export const enumerateCitations = (citations: Citation[]) => {
    const filepathMap = new Map();
    for (const citation of citations) {
        const { filepath } = citation;
        let part_i = 1
        if (filepathMap.has(filepath)) {
            part_i = filepathMap.get(filepath) + 1;
        }
        filepathMap.set(filepath, part_i);
        citation.part_index = part_i;
    }
    return citations;
}

const splitAndReplace = (url: string | null) => {
    const BLOB_ACCOUNT = 'https://datascienceteampocra7fd.blob.core.windows.net'; // Replace with your actual blob account name
    const pattern = new RegExp(`${BLOB_ACCOUNT}/([\\w-]+)/([\\w-]+\\.\\w+)`);
    if (url !== null) {
        const match = url.match(pattern);
        if (match) {
        const container = match[1];
        url = url.replace(container, "trading-bot")
        }
    }
    return url; // or throw an error if you prefer
  };

export function parseAnswer(answer: AskResponse): ParsedAnswer {
    let answerText = answer.answer;
    const citationLinks = answerText.match(/\[(doc\d\d?\d?)]/g);

    const lengthDocN = "[doc".length;
    
    let filteredCitations = [] as Citation[];
    let citationReindex = 0;
    citationLinks?.forEach(link => {
        // Replacing the links/citations with number
        let citationIndex = link.slice(lengthDocN, link.length - 1);
        let citation = cloneDeep(answer.citations[Number(citationIndex) - 1]) as Citation;
        if (!filteredCitations.find((c) => c.id === citationIndex) && citation) {
            answerText = answerText.replaceAll(link, ` ^${++citationReindex}^ `);
            citation.id = citationIndex;
            citation.url = splitAndReplace(citation.url)
            citation.reindex_id = citationReindex.toString();
            let content = citation.content.split("\n")
            citation.content = content[0]
            if (content.length > 1) {
                citation.page = content[1]
            } else {
                citation.page = "1";
            }
            filteredCitations.push(citation);
        }
    })

    filteredCitations = enumerateCitations(filteredCitations);

    return {
        citations: filteredCitations,
        markdownFormatText: answerText
    };
}
