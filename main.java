class Person {
    void display() {
        System.out.println("I am a Person");
    }
}

// Single Inheritance
class Student extends Person {
    void study() {
        System.out.println("Student is studying");
    }
}

// Multilevel Inheritance
class GraduateStudent extends Student {
    void research() {
        System.out.println("Student is doing research");
    }
}

// Hierarchical Inheritance
class Professor extends Person {
    void teach() {
        System.out.println("Professor is teaching");
    }
}

public class Main {
    public static void main(String[] args) {

        Student s = new Student();
        s.display();
        s.study();

        GraduateStudent g = new GraduateStudent();
        g.display();
        g.study();
        g.research();

        Professor p = new Professor();
        p.display();
        p.teach();
    }
}