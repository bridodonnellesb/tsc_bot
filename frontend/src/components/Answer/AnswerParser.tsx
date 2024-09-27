import { AskResponse, Citation } from "../../api";
import { cloneDeep } from "lodash";
import he from "he";

export type ParsedAnswer = {
    citations: Citation[];
    markdownFormatText: string;
    // types_filter: string[];
    // rules_filter: string[];
    // parts_filter: string[];
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

export function parseAnswer(answer: AskResponse): ParsedAnswer {
    let answerText = answer.answer;
    // let answerTypes = answer.types_filter || [];
    // let answerRules = answer.rules_filter || [];
    // let answerParts = answer.parts_filter || [];

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
            let oldTitle = citation.title || "Default Title";
            citation.title = he.decode(oldTitle);
            citation.reindex_id = citationReindex.toString();
            let content = citation.content.split("\n")
            citation.content = content[0]
            if (content.length > 1) {
                citation.page = content[1]
                citation.release_date = content[2]
                citation.version = content[3]
            } else {
                citation.page = "1";
                citation.release_date = "NA"
                citation.version = "NA"
            }
            filteredCitations.push(citation);
        }
    })

    filteredCitations = enumerateCitations(filteredCitations);

    return {
        citations: filteredCitations,
        markdownFormatText: answerText,
        // types_filter: answerTypes,
        // rules_filter: answerRules,
        // parts_filter: answerParts
    };
}
