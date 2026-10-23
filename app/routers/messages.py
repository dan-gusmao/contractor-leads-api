from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..deps import get_current_user, get_db
from ..i18n import AppError
from ..models import Conversation, Message, Project, Role, User
from ..schemas import ConversationOut, MessageIn, MessageOut, StartConversationIn
from ..services.credits import find_unlock

router = APIRouter(tags=["messages"])


def _conversation_out(db: Session, conversation: Conversation) -> ConversationOut:
    project = db.get(Project, conversation.project_id)
    messages = conversation.messages
    return ConversationOut(
        id=conversation.id,
        project_id=conversation.project_id,
        project_title=project.title,
        customer_id=conversation.customer_id,
        contractor_id=conversation.contractor_id,
        last_message_at=messages[-1].created_at if messages else None,
        messages=[MessageOut.model_validate(m) for m in messages],
    )


def _participant_conversation(db: Session, conversation_id: int, user: User) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or user.id not in (conversation.customer_id, conversation.contractor_id):
        raise AppError(404, "conversation.not_found")
    return conversation


@router.post("/projects/{project_id}/conversations", response_model=ConversationOut, status_code=201)
def start_conversation(
    project_id: int,
    data: StartConversationIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConversationOut:
    """Open (or reuse) the conversation between a project's customer and a contractor.

    A contractor starts it for themself; a customer names the contractor.
    Either way the contractor must have unlocked the project.
    """
    project = db.get(Project, project_id)
    if project is None:
        raise AppError(404, "project.not_found")

    if user.role is Role.contractor:
        contractor_id = user.id
    elif user.role is Role.customer and user.id == project.customer_id and data.contractor_id:
        contractor_id = data.contractor_id
    else:
        raise AppError(403, "message.not_allowed")
    if find_unlock(db, contractor_id, project.id) is None:
        raise AppError(403, "message.not_allowed")

    conversation = db.scalar(
        select(Conversation).where(
            Conversation.project_id == project.id, Conversation.contractor_id == contractor_id
        )
    )
    if conversation is None:
        conversation = Conversation(
            project_id=project.id, customer_id=project.customer_id, contractor_id=contractor_id
        )
        db.add(conversation)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            conversation = db.scalar(
                select(Conversation).where(
                    Conversation.project_id == project.id,
                    Conversation.contractor_id == contractor_id,
                )
            )
    db.add(Message(conversation_id=conversation.id, sender_id=user.id, body=data.body.strip()))
    db.commit()
    db.refresh(conversation)
    return _conversation_out(db, conversation)


@router.get("/me/conversations", response_model=list[ConversationOut])
def my_conversations(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[ConversationOut]:
    conversations = db.scalars(
        select(Conversation)
        .where(or_(Conversation.customer_id == user.id, Conversation.contractor_id == user.id))
        .order_by(Conversation.id.desc())
    ).all()
    return [_conversation_out(db, c) for c in conversations]


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ConversationOut:
    return _conversation_out(db, _participant_conversation(db, conversation_id, user))


@router.post(
    "/conversations/{conversation_id}/messages", response_model=MessageOut, status_code=201
)
def send_message(
    conversation_id: int,
    data: MessageIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Message:
    conversation = _participant_conversation(db, conversation_id, user)
    message = Message(conversation_id=conversation.id, sender_id=user.id, body=data.body.strip())
    db.add(message)
    db.commit()
    return message
